
        let currentSelectedPhone = null;
        let allConversations = [];
        let allTemplates = [];
        let lastLogVersion = -1;

        function switchTab(tabId, btnEl) {
            try {
                document.querySelectorAll('.tab-btn').forEach(function(btn) { btn.classList.remove('active'); });
                document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
                
                var targetTab = document.getElementById('tab-' + tabId);
                if (targetTab) targetTab.classList.add('active');
                
                if (btnEl) {
                    btnEl.classList.add('active');
                } else {
                    var btn = document.querySelector('.tab-btn[data-tab="' + tabId + '"]');
                    if (btn) btn.classList.add('active');
                }

                if (tabId === 'messenger') {
                    loadConversations();
                    loadDevices();
                } else if (tabId === 'logs') {
                    loadHistoryTable();
                    loadAndroidEventsTable();
                }
            } catch (e) {
                console.error("switchTab error:", e);
            }
        }

        function escapeHtml(val) {
            if (val === null || val === undefined) return '';
            return String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        async function runAction(path) {
            try {
                if (path === '/connect') {
                    var statusText = document.getElementById('service-status-text');
                    if (statusText) statusText.textContent = 'SMS Service: Đang quét thiết bị...';
                }
                var response = await fetch(path, { method: 'POST' });
                var data = await response.json();
                if (!response.ok) {
                    alert(data.message || data.status || 'Yêu cầu thất bại');
                } else if (path === '/connect') {
                    alert('✅ Kết nối thành công!\n- Thiết bị Android: ' + (data.android || 0) + '\n- USB Modem: ' + (data.modems || 0));
                }
                await updateStatusAndLogs();
                await loadDevices();
                await loadConversations();
            } catch (e) {
                alert('Lỗi kết nối: ' + e);
            }
        }

        function downloadHistory() {
            window.location.href = '/history.csv';
        }

        function exitTool() {
            if (!confirm('Bạn có chắc chắn muốn thoát hoàn toàn công cụ?')) return;
            fetch('/shutdown', { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function() {
                    alert('Ứng dụng đang tắt...');
                    window.close();
                });
        }

        // LOAD DEVICES & POPULATE COMPOSER SELECT
        async function loadDevices() {
            try {
                var res = await fetch('/api/devices');
                if (!res.ok) return;
                var data = await res.json();
                var select = document.getElementById('composer-device');
                if (!select) return;
                var currentVal = select.value;
                select.innerHTML = '<option value="AUTO">Tự động (Khuyên dùng)</option>';

                (data.android_devices || []).forEach(function(d) {
                    var opt = document.createElement('option');
                    opt.value = d.serial;
                    opt.textContent = '📱 Android: ' + d.model + ' (' + d.serial + ') ' + (d.ready ? '✅ Sẵn sàng' : '⚠️ Chưa sẵn sàng');
                    select.appendChild(opt);
                });

                (data.usb_modems || []).forEach(function(m) {
                    var opt = document.createElement('option');
                    opt.value = m.port;
                    opt.textContent = '📶 USB Modem: ' + m.port + ' (📶 ' + m.signal + ')';
                    select.appendChild(opt);
                });

                var hasOption = Array.from(select.options).some(function(o) { return o.value === currentVal; });
                if (hasOption) {
                    select.value = currentVal;
                }
            } catch (e) {
                console.error("loadDevices error:", e);
            }
        }

        // LOAD TEMPLATES
        async function loadTemplates() {
            try {
                var res = await fetch('/api/templates');
                if (!res.ok) return;
                var data = await res.json();
                allTemplates = data.templates || [];
                var select = document.getElementById('template-select');
                if (!select) return;
                select.innerHTML = '<option value="">⚡ Chọn mẫu tin nhắn từ thư mục messages...</option>';
                allTemplates.forEach(function(t, i) {
                    var opt = document.createElement('option');
                    opt.value = i;
                    var preview = (t && t.content) ? t.content.substring(0, 45) : '';
                    var name = (t && t.name) ? t.name : 'Mẫu';
                    opt.textContent = '📄 ' + name + ' - ' + preview + '...';
                    select.appendChild(opt);
                });
            } catch (e) {
                console.error("loadTemplates error:", e);
            }
        }

        function insertTemplate() {
            var select = document.getElementById('template-select');
            if (!select) return;
            var idx = select.value;
            if (idx === '') return;
            var t = allTemplates[idx];
            if (!t) return;
            var nameInput = document.getElementById('composer-name');
            var name = (nameInput && nameInput.value.trim()) ? nameInput.value.trim() : 'Anh/Chị';
            var content = (t.content || '').replace(/\{name\}/g, name);
            var msgInput = document.getElementById('composer-msg');
            if (msgInput) {
                msgInput.value = content;
                updateCharCount();
            }
        }

        // LOAD CONVERSATIONS
        async function loadConversations() {
            try {
                var res = await fetch('/api/conversations');
                if (!res.ok) return;
                var data = await res.json();
                allConversations = data.conversations || [];
                renderConversationList(allConversations);
            } catch (e) {
                console.error("loadConversations error:", e);
            }
        }

        function filterConversations() {
            var searchInput = document.getElementById('conv-search');
            var query = (searchInput ? searchInput.value : '').toLowerCase().trim();
            if (!query) {
                renderConversationList(allConversations);
                return;
            }
            var filtered = allConversations.filter(function(c) {
                return (c.phone && c.phone.toLowerCase().includes(query)) ||
                       (c.customer_name && c.customer_name.toLowerCase().includes(query)) ||
                       (c.message && c.message.toLowerCase().includes(query));
            });
            renderConversationList(filtered);
        }

        function onConvItemClick(el) {
            var phone = decodeURIComponent(el.getAttribute('data-phone') || '');
            var name = decodeURIComponent(el.getAttribute('data-name') || '');
            selectConversation(phone, name);
        }

        function renderConversationList(list) {
            var container = document.getElementById('conv-list');
            if (!container) return;
            if (!list.length) {
                container.innerHTML = '<li style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Chưa có cuộc hội thoại nào.</li>';
                return;
            }
            container.innerHTML = list.map(function(c) {
                var isActive = currentSelectedPhone && c.phone === currentSelectedPhone;
                var initial = (c.customer_name && c.customer_name.trim()) ? c.customer_name.trim().charAt(0).toUpperCase() : 'S';
                var statusBadge = '';
                if (c.status === 'MODEM_ACCEPTED' || c.status === 'DELIVERED' || c.status === 'ANDROID_ACCEPTED') {
                    statusBadge = '<span class="conv-badge badge-ok">Thành công</span>';
                } else if (c.status === 'FAILED' || c.status === 'ERROR') {
                    statusBadge = '<span class="conv-badge badge-fail">Thất bại</span>';
                } else {
                    statusBadge = '<span class="conv-badge badge-pending">Đang gửi</span>';
                }

                return '<li class="conv-item ' + (isActive ? 'active' : '') + '" data-phone="' + encodeURIComponent(c.phone || '') + '" data-name="' + encodeURIComponent(c.customer_name || '') + '" onclick="onConvItemClick(this)">' +
                    '<div class="conv-avatar">' + initial + '</div>' +
                    '<div class="conv-details">' +
                        '<div class="conv-top-row">' +
                            '<span class="conv-name">' + escapeHtml(c.customer_name || 'Khách hàng') + '</span>' +
                            '<span class="conv-time">' + escapeHtml(c.updated_at ? c.updated_at.substring(11, 16) : '') + '</span>' +
                        '</div>' +
                        '<div class="conv-phone">' + escapeHtml(c.phone) + '</div>' +
                        '<div class="conv-preview">' + escapeHtml(c.message || '') + '</div>' +
                        '<div class="conv-meta">' +
                            '<span style="font-size:11px;color:var(--text-muted);">' + (c.total_count || 1) + ' tin nhắn</span>' +
                            statusBadge +
                        '</div>' +
                    '</div>' +
                '</li>';
            }).join('');
        }

        async function selectConversation(phone, name) {
            currentSelectedPhone = phone;
            var phoneInput = document.getElementById('composer-phone');
            var nameInput = document.getElementById('composer-name');
            var chatTitle = document.getElementById('chat-title');
            var chatSubtitle = document.getElementById('chat-subtitle');
            var chatAvatar = document.getElementById('chat-avatar');

            if (phoneInput) phoneInput.value = phone;
            if (nameInput) nameInput.value = name;
            if (chatTitle) chatTitle.textContent = (name || 'Khách hàng') + ' (' + phone + ')';
            if (chatSubtitle) chatSubtitle.textContent = 'Lịch sử tin nhắn SMS trực tiếp';
            if (chatAvatar) chatAvatar.textContent = (name && name.trim()) ? name.trim().charAt(0).toUpperCase() : 'S';

            renderConversationList(allConversations);
            await loadChatMessages(phone);
        }

        async function loadChatMessages(phone) {
            try {
                var res = await fetch('/api/messages?phone=' + encodeURIComponent(phone));
                if (!res.ok) return;
                var data = await res.json();
                var container = document.getElementById('chat-history');
                if (!container) return;
                var messages = data.messages || [];

                if (!messages.length) {
                    container.innerHTML = '<div class="empty-chat"><p>Chưa có tin nhắn nào với số <b>' + escapeHtml(phone) + '</b>. Hãy soạn tin bên dưới để bắt đầu gửi.</p></div>';
                    return;
                }

                container.innerHTML = messages.map(function(m) {
                    var statusClass = 'badge-pending';
                    var statusText = m.status;
                    if (m.status === 'MODEM_ACCEPTED' || m.status === 'DELIVERED' || m.status === 'ANDROID_ACCEPTED') {
                        statusClass = 'badge-ok';
                        statusText = m.delivery_status === 'DELIVERED' ? 'ĐÃ NHẬN (DELIVERED)' : 'ĐÃ GỬI (ACCEPTED)';
                    } else if (m.status === 'FAILED' || m.status === 'ERROR') {
                        statusClass = 'badge-fail';
                        statusText = 'THẤT BẠI';
                    }

                    return '<div class="bubble-group">' +
                        '<div class="chat-bubble">' + escapeHtml(m.message) + '</div>' +
                        '<div class="bubble-meta">' +
                            '<span>🕒 ' + escapeHtml(m.created_at || m.updated_at || '') + '</span>' +
                            '<span>• ' + escapeHtml(m.transport || 'SMS') + ' (' + escapeHtml(m.device_id || m.modem_port || '') + ')</span>' +
                            '<span class="bubble-tag ' + statusClass + '">' + escapeHtml(statusText) + '</span>' +
                        '</div>' +
                    '</div>';
                }).join('');

                container.scrollTop = container.scrollHeight;
            } catch (e) {
                console.error("loadChatMessages error:", e);
            }
        }

        function openNewComposer() {
            currentSelectedPhone = null;
            var phoneInput = document.getElementById('composer-phone');
            var nameInput = document.getElementById('composer-name');
            var msgInput = document.getElementById('composer-msg');
            var chatTitle = document.getElementById('chat-title');
            var chatSubtitle = document.getElementById('chat-subtitle');
            var chatAvatar = document.getElementById('chat-avatar');
            var chatHistory = document.getElementById('chat-history');

            if (phoneInput) phoneInput.value = '';
            if (nameInput) nameInput.value = '';
            if (msgInput) msgInput.value = '';
            if (chatTitle) chatTitle.textContent = 'Soạn tin nhắn mới';
            if (chatSubtitle) chatSubtitle.textContent = 'Nhập số điện thoại và nội dung bên dưới';
            if (chatAvatar) chatAvatar.textContent = '✉️';
            if (chatHistory) {
                chatHistory.innerHTML = '<div class="empty-chat"><p>Nhập số điện thoại và soạn nội dung bên dưới để gửi tin nhắn mới.</p></div>';
            }
            renderConversationList(allConversations);
            updateCharCount();
            if (phoneInput) phoneInput.focus();
        }

        function onComposerPhoneChange() {
            var phoneInput = document.getElementById('composer-phone');
            var phone = (phoneInput ? phoneInput.value : '').trim();
            var chatTitle = document.getElementById('chat-title');
            if (chatTitle && phone.length >= 9) {
                chatTitle.textContent = 'Gửi tới: ' + phone;
            }
        }

        function onComposerNameChange() {}

        function updateCharCount() {
            var msgInput = document.getElementById('composer-msg');
            var msg = msgInput ? msgInput.value : '';
            var len = msg.length;
            var isUnicode = /[^\u0000-\u007f]/.test(msg);
            var partSize = isUnicode ? (len > 70 ? 67 : 70) : (len > 160 ? 153 : 160);
            var parts = len === 0 ? 1 : Math.ceil(len / partSize);
            var type = isUnicode ? 'Unicode' : 'GSM';
            
            var counter = document.getElementById('char-counter');
            if (counter) {
                counter.textContent = 'Độ dài: ' + len + ' ký tự | ' + parts + ' tin (' + type + ')';
                if (parts > 1) {
                    counter.classList.add('limit');
                } else {
                    counter.classList.remove('limit');
                }
            }
        }

        function clearComposer() {
            var msgInput = document.getElementById('composer-msg');
            if (msgInput) msgInput.value = '';
            updateCharCount();
        }

        async function sendDirectMessage() {
            var phoneInput = document.getElementById('composer-phone');
            var msgInput = document.getElementById('composer-msg');
            var nameInput = document.getElementById('composer-name');
            var devSelect = document.getElementById('composer-device');

            var phone = phoneInput ? phoneInput.value.trim() : '';
            var message = msgInput ? msgInput.value.trim() : '';
            var name = (nameInput && nameInput.value.trim()) ? nameInput.value.trim() : 'Anh/Chị';
            var device = devSelect ? devSelect.value : 'AUTO';

            if (!phone) {
                alert('Vui lòng nhập số điện thoại nhận!');
                if (phoneInput) phoneInput.focus();
                return;
            }
            if (!message) {
                alert('Vui lòng nhập nội dung tin nhắn!');
                if (msgInput) msgInput.focus();
                return;
            }

            var sendBtn = document.getElementById('btn-send-sms');
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.innerHTML = '<span>⏳ Đang gửi...</span>';
            }

            try {
                var payload = {
                    phone: phone,
                    message: message,
                    name: name,
                    device_id: device === 'AUTO' ? null : device,
                    transport: device === 'AUTO' ? 'AUTO' : (device.startsWith('COM') ? 'USB_MODEM' : 'ANDROID')
                };

                var res = await fetch('/api/send_sms', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                var data = await res.json();
                if (!res.ok) {
                    alert('Gửi tin thất bại: ' + (data.message || 'Lỗi không xác định'));
                } else {
                    if (msgInput) msgInput.value = '';
                    updateCharCount();
                    currentSelectedPhone = phone;
                    await loadConversations();
                    await loadChatMessages(phone);
                }
            } catch (e) {
                alert('Lỗi kết nối khi gửi: ' + e);
            } finally {
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.innerHTML = '<span>🚀 GỬI TIN NHẮN</span>';
                }
            }
        }

        // REFRESH STATUS & LOGS LOOP
        async function updateStatusAndLogs() {
            try {
                var res = await fetch('/log');
                if (!res.ok) throw new Error('HTTP ' + res.status);
                var d = await res.json();

                // 1. Update Service Status Bar
                var badge = document.getElementById('service-status-badge');
                var text = document.getElementById('service-status-text');
                if (badge) badge.className = 'status-badge';
                if (text) text.textContent = 'SMS Service: Đang kết nối (Online)';

                var readyAndroid = (d.android_devices || []).filter(function(x) { return x.ready; }).length;
                var totalAndroid = (d.android_devices || []).length;
                var usbCount = Object.keys(d.signals || {}).length;

                var tagAndroid = document.getElementById('stat-android-tag');
                if (tagAndroid) tagAndroid.textContent = '📱 Android: ' + readyAndroid + '/' + totalAndroid + ' sẵn sàng';

                var tagModem = document.getElementById('stat-modem-tag');
                if (tagModem) tagModem.textContent = '📶 USB Modem: ' + usbCount + ' sẵn sàng';

                var adb = d.adb || {};
                var adbText = 'ADB: Chưa cài';
                if (adb.status === 'device') adbText = 'ADB: Sẵn sàng (' + (adb.devices || []).length + ' máy)';
                else if (adb.status === 'unauthorized') adbText = 'ADB: Cần cấp quyền USB';
                else if (adb.available) adbText = 'ADB: ' + adb.status;

                var tagAdb = document.getElementById('stat-adb-tag');
                if (tagAdb) tagAdb.textContent = adbText;

                // 2. Update Campaign Stats
                var statTotal = document.getElementById('stat-total');
                if (statTotal) statTotal.textContent = d.sent + '/' + d.total;
                
                var statSuccess = document.getElementById('stat-success');
                if (statSuccess) statSuccess.textContent = d.success;

                var statFail = document.getElementById('stat-fail');
                if (statFail) statFail.textContent = Math.max(0, d.sent - d.success);

                var pBar = document.getElementById('pbar');
                if (pBar) {
                    if (d.total > 0) {
                        pBar.max = d.total;
                        pBar.value = d.sent;
                    } else {
                        pBar.value = 0;
                    }
                }

                // 3. Update Device List Cards in Tab 2
                var deviceList = document.getElementById('device-list');
                if (deviceList) {
                    var usbCards = Object.entries(d.signals || {}).map(function(entry) {
                        var port = entry[0], sig = entry[1];
                        return '<div class="modem-card ready"><b>📶 USB MODEM</b><br>Cổng: ' + escapeHtml(port) + '<br>Sóng: 📶 ' + escapeHtml(sig) + '</div>';
                    });
                    var androidCards = (d.android_devices || []).map(function(device) {
                        var simHtml = '';
                        if (device.sims && device.sims.length > 0) {
                            var items = device.sims.map(function(s, idx) {
                                var simNum = (s.slot_index !== undefined ? s.slot_index + 1 : idx + 1);
                                var carrier = s.carrier_name || s.display_name || ('SIM ' + simNum);
                                var inService = s.in_service !== false;
                                return '<div style="margin-top:2px;font-size:12px;">' +
                                    '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (inService ? '#00e676' : '#ff5252') + ';margin-right:4px;"></span>' +
                                    '<b>SIM ' + simNum + ':</b> ' + escapeHtml(carrier) +
                                    (inService ? ' <span style="color:#00e676;font-size:11px;">(Sẵn sàng)</span>' : ' <span style="color:#ff5252;font-size:11px;">(Mất sóng)</span>') +
                                    '</div>';
                            }).join('');
                            simHtml = '<div style="margin-top:6px;padding-top:6px;border-top:1px dashed rgba(255,255,255,0.2);">' +
                                '<div style="font-weight:bold;color:#38bdf8;font-size:12px;margin-bottom:2px;">📶 ' + (device.sims.length > 1 ? device.sims.length + ' SIM (Dual SIM)' : '1 SIM') + '</div>' +
                                items +
                                '</div>';
                        } else if (device.ready) {
                            simHtml = '<div style="margin-top:6px;padding-top:6px;border-top:1px dashed rgba(255,255,255,0.2);">' +
                                '<div style="margin-top:2px;font-size:12px;">' +
                                '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#00e676;margin-right:4px;"></span>' +
                                '<b>SIM 1:</b> SIM hệ thống mặc định <span style="color:#00e676;font-size:11px;">(Sẵn sàng)</span>' +
                                '</div></div>';
                        }
                        return '<div class="modem-card ' + (device.ready ? 'ready' : 'offline') + '">' +
                            '<b>📱 ANDROID ' + escapeHtml(device.model) + '</b><br>' +
                            'Serial: ' + escapeHtml(device.serial) + '<br>' +
                            'Trạng thái: ' + escapeHtml(device.detail) +
                            simHtml +
                            '</div>';
                    });
                    var allCards = usbCards.concat(androidCards);
                    if (allCards.length) {
                        deviceList.innerHTML = allCards.join('');
                    } else {
                        deviceList.innerHTML = '<div class="modem-card offline">Chưa có thiết bị. Bấm QUÉT THIẾT BỊ.</div>';
                    }
                }

                // 4. Update Logs
                if (d.version !== lastLogVersion) {
                    lastLogVersion = d.version;
                    var logBox = document.getElementById('log-box');
                    if (logBox && d.logs && d.logs.length) {
                        logBox.textContent = d.logs.join('\n');
                        logBox.scrollTop = logBox.scrollHeight;
                    }
                }
            } catch (e) {
                console.error("updateStatusAndLogs error:", e);
                var badgeEl = document.getElementById('service-status-badge');
                var textEl = document.getElementById('service-status-text');
                if (badgeEl) badgeEl.className = 'status-badge error';
                if (textEl) textEl.textContent = 'SMS Service: Mất kết nối';
            }
        }

        async function loadHistoryTable() {
            try {
                var res = await fetch('/history');
                if (!res.ok) return;
                var data = await res.json();
                var tbody = document.querySelector('#history-table tbody');
                if (!tbody) return;
                tbody.innerHTML = (data.rows || []).map(function(r) {
                    var statusClass = (r.status === 'MODEM_ACCEPTED' || r.status === 'DELIVERED' || r.status === 'ANDROID_ACCEPTED') ? 'status-ok' : 'status-fail';
                    return '<tr>' +
                        '<td>' + escapeHtml(r.updated_at) + '</td>' +
                        '<td><b>' + escapeHtml(r.phone) + '</b></td>' +
                        '<td>' + escapeHtml(r.customer_name) + '</td>' +
                        '<td>' + escapeHtml(r.transport) + '</td>' +
                        '<td>' + escapeHtml(r.device_id || r.modem_port) + '</td>' +
                        '<td>' + escapeHtml(r.message_ref) + '</td>' +
                        '<td class="' + statusClass + '">' + escapeHtml(r.status) + '</td>' +
                        '<td>' + escapeHtml(r.delivery_status) + '</td>' +
                        '<td>' + escapeHtml(r.message) + '</td>' +
                        '<td>' + escapeHtml(r.modem_response) + '</td>' +
                    '</tr>';
                }).join('');
            } catch (e) {
                console.error("loadHistoryTable error:", e);
            }
        }

        async function loadAndroidEventsTable() {
            try {
                var res = await fetch('/android-events');
                if (!res.ok) return;
                var data = await res.json();
                var tbody = document.querySelector('#android-events-table tbody');
                if (!tbody) return;
                tbody.innerHTML = (data.rows || []).map(function(r) {
                    var statusClass = (r.status === 'FAILED' || r.status === 'ERROR') ? 'status-fail' : 'status-ok';
                    return '<tr>' +
                        '<td>' + escapeHtml(r.device_id || r.model) + '</td>' +
                        '<td>' + escapeHtml(r.job_id) + '</td>' +
                        '<td>' + escapeHtml(r.latest_stage) + '</td>' +
                        '<td class="' + statusClass + '">' + escapeHtml(r.status) + '</td>' +
                        '<td>' + escapeHtml(r.error) + '</td>' +
                        '<td>' + escapeHtml(r.response) + '</td>' +
                    '</tr>';
                }).join('');
            } catch (e) {
                console.error("loadAndroidEventsTable error:", e);
            }
        }

        // Init
        loadTemplates();
        loadDevices();
        loadConversations();
        updateStatusAndLogs();
        setInterval(updateStatusAndLogs, 3000);
        setInterval(function() {
            if (currentSelectedPhone) loadChatMessages(currentSelectedPhone);
            loadConversations();
        }, 5000);
    