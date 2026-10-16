package vn.smsbridge.desktop;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import org.apache.poi.ss.usermodel.*;
import org.json.JSONArray;
import org.json.JSONObject;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.border.LineBorder;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Cursor;
import java.awt.Desktop;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.GridLayout;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;

public final class SmsSenderDesktop extends JFrame {
    private static final int DEFAULT_PORT = 8899;
    private static int activePort = DEFAULT_PORT;
    private static String appUrl = "http://127.0.0.1:" + DEFAULT_PORT;

    private static final AdbClient adb = new AdbClient();
    private static final CampaignService campaign = new CampaignService(SmsSenderDesktop::executeSendSms);
    private static final ZaloLauncher zalo = new ZaloLauncher(
        Path.of(System.getProperty("user.home"), ".sms-sender-tool", "zalo_profiles")
    );

    // In-memory data store
    private static final List<String> recentLogs = new CopyOnWriteArrayList<>();
    private static final List<HistoryItem> historyList = new CopyOnWriteArrayList<>();
    private static final List<JSONObject> androidEvents = new CopyOnWriteArrayList<>();
    private static final Map<String, JSONObject> cloudDevices = new ConcurrentHashMap<>();
    private static final Map<String, List<JSONObject>> cloudJobs = new ConcurrentHashMap<>();
    private static final Map<String, CompletableFuture<Boolean>> pendingJobFutures = new ConcurrentHashMap<>();
    private static final Path messagesDir = resolveMessagesDir();
    private static Path uploadedExcelPath = null;
    private static JSONObject campaignInfoCache = new JSONObject();

    public static List<JSONObject> getActiveCloudDevices() {
        long now = System.currentTimeMillis();
        List<JSONObject> active = new ArrayList<>();
        for (var entry : cloudDevices.entrySet()) {
            JSONObject d = entry.getValue();
            if (now - d.optLong("last_seen", 0) <= 35000L) {
                active.add(d);
            }
        }
        return active;
    }

    private final JLabel lblStatus = new JLabel("Khởi động...");
    private final JLabel lblAdb = new JLabel("ADB: Đang quét...");
    private final JTextArea txtLog = new JTextArea();

    public static final class HistoryItem {
        private final String updated_at;
        private final String phone;
        private final String customer_name;
        private final String transport;
        private final String device_id;
        private final String message_ref;
        private final String status;
        private final String delivery_status;
        private final String message;
        private final String modem_response;

        public HistoryItem(
            String updated_at,
            String phone,
            String customer_name,
            String transport,
            String device_id,
            String message_ref,
            String status,
            String delivery_status,
            String message,
            String modem_response
        ) {
            this.updated_at = updated_at != null ? updated_at : "";
            this.phone = phone != null ? phone : "";
            this.customer_name = customer_name != null ? customer_name : "";
            this.transport = transport != null ? transport : "";
            this.device_id = device_id != null ? device_id : "";
            this.message_ref = message_ref != null ? message_ref : "";
            this.status = status != null ? status : "";
            this.delivery_status = delivery_status != null ? delivery_status : "";
            this.message = message != null ? message : "";
            this.modem_response = modem_response != null ? modem_response : "";
        }

        public String updated_at() { return updated_at; }
        public String phone() { return phone; }
        public String customer_name() { return customer_name; }
        public String transport() { return transport; }
        public String device_id() { return device_id; }
        public String message_ref() { return message_ref; }
        public String status() { return status; }
        public String delivery_status() { return delivery_status; }
        public String message() { return message; }
        public String modem_response() { return modem_response; }
    }

    public static void main(String[] args) {
        // 1. Khởi động Embedded HttpServer hoàn toàn độc lập (không cần Python/Flask)
        startEmbeddedServer();
        startUdpDiscoveryResponder();

        // 2. Mở trình duyệt giao diện đầy đủ (ưu tiên App mode của Edge/Chrome)
        openBrowserUI(appUrl);

        // 3. Hiển thị cửa sổ điều khiển Java Swing
        SwingUtilities.invokeLater(() -> {
            try {
                UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
            } catch (Exception ignored) {}
            new SmsSenderDesktop().setVisible(true);
        });
    }

    private SmsSenderDesktop() {
        super("SMS Sender Tool (Standalone Java)");
        setDefaultCloseOperation(EXIT_ON_CLOSE);
        setMinimumSize(new Dimension(680, 480));
        setSize(760, 520);
        setLocationRelativeTo(null);

        JPanel root = new JPanel(new BorderLayout(0, 12));
        root.setBackground(Color.decode("#0F172A"));
        root.setBorder(new EmptyBorder(16, 20, 20, 20));

        // Header
        JPanel header = new JPanel(new GridLayout(0, 1, 4, 4));
        header.setOpaque(false);
        JLabel title = new JLabel("📱 SMS Sender Tool (Phiên bản Độc lập Java)");
        title.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 18));
        title.setForeground(Color.decode("#38BDF8"));
        header.add(title);

        lblStatus.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 13));
        lblStatus.setForeground(Color.decode("#4ADE80"));
        lblStatus.setText("🟢 Máy chủ Java đang chạy tại: " + appUrl);
        header.add(lblStatus);

        lblAdb.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 12));
        lblAdb.setForeground(Color.decode("#94A3B8"));
        header.add(lblAdb);
        root.add(header, BorderLayout.NORTH);

        // Action Buttons
        JPanel actionPanel = new JPanel(new GridLayout(1, 3, 10, 0));
        actionPanel.setOpaque(false);

        JButton btnOpen = new JButton("🌐 Mở Giao Diện Web");
        btnOpen.setBackground(Color.decode("#0284C7"));
        btnOpen.setForeground(Color.WHITE);
        btnOpen.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 13));
        btnOpen.setCursor(new Cursor(Cursor.HAND_CURSOR));
        btnOpen.addActionListener(e -> openBrowserUI(appUrl));

        JButton btnScan = new JButton("🔄 Quét Thiết Bị");
        btnScan.setBackground(Color.decode("#334155"));
        btnScan.setForeground(Color.WHITE);
        btnScan.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 13));
        btnScan.setCursor(new Cursor(Cursor.HAND_CURSOR));
        btnScan.addActionListener(e -> refreshDevices());

        JButton btnExit = new JButton("🛑 Thoát Ứng Dụng");
        btnExit.setBackground(Color.decode("#EF4444"));
        btnExit.setForeground(Color.WHITE);
        btnExit.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 13));
        btnExit.setCursor(new Cursor(Cursor.HAND_CURSOR));
        btnExit.addActionListener(e -> System.exit(0));

        actionPanel.add(btnOpen);
        actionPanel.add(btnScan);
        actionPanel.add(btnExit);

        JPanel centerPanel = new JPanel(new BorderLayout(0, 10));
        centerPanel.setOpaque(false);
        centerPanel.add(actionPanel, BorderLayout.NORTH);

        txtLog.setEditable(false);
        txtLog.setBackground(Color.decode("#1E293B"));
        txtLog.setForeground(Color.decode("#CBD5E1"));
        txtLog.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 11));
        txtLog.setBorder(new EmptyBorder(8, 8, 8, 8));
        JScrollPane scrollLog = new JScrollPane(txtLog);
        scrollLog.setBorder(new LineBorder(Color.decode("#334155"), 1, true));
        centerPanel.add(scrollLog, BorderLayout.CENTER);

        root.add(centerPanel, BorderLayout.CENTER);
        setContentPane(root);

        refreshDevices();
        new javax.swing.Timer(3000, e -> updateLogBox()).start();
    }

    private void refreshDevices() {
        new Thread(() -> {
            var devs = adb.listDevices();
            SwingUtilities.invokeLater(() -> {
                if (adb.isAvailable()) {
                    lblAdb.setText("📱 ADB Sẵn sàng: " + devs.size() + " thiết bị kết nối");
                } else {
                    lblAdb.setText("⚠️ ADB chưa sẵn sàng (đang dùng chế độ dự phòng)");
                }
            });
            appendLog("Quét ADB: tìm thấy " + devs.size() + " thiết bị Android");
        }).start();
    }

    private void updateLogBox() {
        if (!recentLogs.isEmpty()) {
            StringBuilder sb = new StringBuilder();
            int start = Math.max(0, recentLogs.size() - 40);
            for (int i = start; i < recentLogs.size(); i++) {
                sb.append(recentLogs.get(i)).append("\n");
            }
            txtLog.setText(sb.toString());
            txtLog.setCaretPosition(txtLog.getDocument().getLength());
        }
    }

    public static void appendLog(String line) {
        String entry = "[" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm:ss")) + "] " + line;
        recentLogs.add(entry);
        if (recentLogs.size() > 500) recentLogs.remove(0);
    }

    private static void openBrowserUI(String url) {
        new Thread(() -> {
            try {
                String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
                if (os.contains("win")) {
                    try {
                        new ProcessBuilder("msedge", "--app=" + url).start();
                        return;
                    } catch (Exception ignored) {}
                    try {
                        new ProcessBuilder("chrome", "--app=" + url).start();
                        return;
                    } catch (Exception ignored) {}
                } else if (os.contains("mac")) {
                    try {
                        new ProcessBuilder("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--app=" + url).start();
                        return;
                    } catch (Exception ignored) {}
                }
                if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE)) {
                    Desktop.getDesktop().browse(URI.create(url));
                }
            } catch (Exception e) {
                appendLog("Lỗi mở trình duyệt: " + e.getMessage());
            }
        }).start();
    }

    private static Path resolveMessagesDir() {
        Path p = Paths.get("messages");
        if (!Files.isDirectory(p)) {
            p = Paths.get(System.getProperty("user.home"), ".sms-sender-tool", "messages");
            try {
                Files.createDirectories(p);
            } catch (Exception ignored) {}
        }
        initDefaultTemplates(p);
        return p;
    }

    private static void initDefaultTemplates(Path dir) {
        try {
            Path f1 = dir.resolve("mau_chao_hoi.txt");
            if (!Files.exists(f1)) {
                Files.writeString(f1, "Xin chào {name}, chúc bạn một ngày làm việc hiệu quả và nhiều niềm vui!", StandardCharsets.UTF_8);
            }
            Path f2 = dir.resolve("mau_khuyen_mai.txt");
            if (!Files.exists(f2)) {
                Files.writeString(f2, "Kính gửi {name}, ưu đãi đặc biệt giảm 20% duy nhất hôm nay dành cho bạn. Liên hệ ngay để nhận quà!", StandardCharsets.UTF_8);
            }
        } catch (Exception ignored) {}
    }

    // ==========================================
    // EMBEDDED HTTP SERVER (100% PURE JAVA)
    // ==========================================

    private static void startEmbeddedServer() {
        for (int p = DEFAULT_PORT; p < DEFAULT_PORT + 30; p++) {
            try {
                HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", p), 0);
                server.setExecutor(Executors.newCachedThreadPool());
                registerEndpoints(server);
                server.start();
                activePort = p;
                appUrl = "http://127.0.0.1:" + activePort;
                appendLog("Máy chủ Web độc lập Java đã khởi động thành công trên cổng " + activePort);
                return;
            } catch (IOException e) {
                // Port occupied, try next
            }
        }
        appendLog("Lỗi: Không tìm thấy cổng mạng khả dụng cho máy chủ Web!");
    }

    private static void registerEndpoints(HttpServer server) {
        // 1. Root & Static HTML
        server.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            if ("/".equals(path) || "/index.html".equals(path)) {
                byte[] html = loadWebIndexHtml();
                sendResponse(exchange, 200, "text/html; charset=utf-8", html);
            } else {
                sendResponse(exchange, 404, "text/plain", "Not Found".getBytes(StandardCharsets.UTF_8));
            }
        });

        server.createContext("/download/apk", exchange -> handleApkDownload(exchange));
        server.createContext("/app", exchange -> handleApkDownload(exchange));

        // 2. Realtime Log & System status
        server.createContext("/log", exchange -> {
            JSONObject obj = new JSONObject();
            obj.put("sent", campaign.getSentCount());
            obj.put("total", campaign.getTotalCount());
            obj.put("success", campaign.getSuccessCount());
            obj.put("running", campaign.isRunning());

            int start = Math.max(0, recentLogs.size() - 50);
            List<String> logsSlice = new ArrayList<>();
            for (int i = start; i < recentLogs.size(); i++) {
                logsSlice.add(recentLogs.get(i));
            }
            obj.put("logs", new JSONArray(logsSlice));

            JSONArray devArray = new JSONArray();
            List<String> devSerials = new ArrayList<>();
            for (var d : adb.listDevices()) {
                JSONObject devJson = new JSONObject();
                devJson.put("serial", d.serial());
                devJson.put("model", d.model());
                devJson.put("ready", d.ready());
                devArray.put(devJson);
                devSerials.add(d.serial());
            }
            for (var cd : getActiveCloudDevices()) {
                String devId = cd.optString("id", "android-01");
                String ip = cd.optString("ip", "");
                JSONObject devJson = new JSONObject();
                devJson.put("serial", "cloud:" + devId);
                devJson.put("model", "Wi-Fi App: " + devId + (ip.isEmpty() ? "" : " (" + ip + ")"));
                devJson.put("ready", true);
                devJson.put("detail", "ready");
                devArray.put(devJson);
                devSerials.add("cloud:" + devId);
            }
            obj.put("android_devices", devArray);
            obj.put("signals", new JSONObject());

            JSONObject adbStatus = new JSONObject();
            adbStatus.put("available", adb.isAvailable());
            adbStatus.put("devices", new JSONArray(devSerials));
            obj.put("adb", adbStatus);

            sendJson(exchange, obj);
        });

        // 3. Devices API
        server.createContext("/api/devices", exchange -> {
            JSONObject obj = new JSONObject();
            JSONArray devArray = new JSONArray();
            for (var d : adb.listDevices()) {
                JSONObject devJson = new JSONObject();
                devJson.put("serial", d.serial());
                devJson.put("model", d.model());
                devJson.put("ready", d.ready());
                devArray.put(devJson);
            }
            for (var cd : getActiveCloudDevices()) {
                String devId = cd.optString("id", "android-01");
                String ip = cd.optString("ip", "");
                JSONObject devJson = new JSONObject();
                devJson.put("serial", "cloud:" + devId);
                devJson.put("model", "Wi-Fi App: " + devId + (ip.isEmpty() ? "" : " (" + ip + ")"));
                devJson.put("ready", true);
                devJson.put("detail", "ready");
                devArray.put(devJson);
            }
            obj.put("devices", devArray);
            obj.put("android_devices", devArray);
            obj.put("ports", new JSONArray());
            sendJson(exchange, obj);
        });

        // 4. Templates APIs
        server.createContext("/api/templates", exchange -> {
            JSONArray list = new JSONArray();
            try {
                if (Files.isDirectory(messagesDir)) {
                    try (var stream = Files.list(messagesDir)) {
                        stream.filter(p -> p.toString().endsWith(".txt"))
                            .sorted()
                            .forEach(p -> {
                                try {
                                    JSONObject t = new JSONObject();
                                    t.put("name", p.getFileName().toString());
                                    t.put("content", Files.readString(p, StandardCharsets.UTF_8).trim());
                                    list.put(t);
                                } catch (Exception ignored) {}
                            });
                    }
                }
            } catch (Exception ignored) {}
            sendJson(exchange, new JSONObject().put("templates", list));
        });

        server.createContext("/api/save_template", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = new JSONObject(body);
                    String content = req.optString("content", "").trim();
                    String name = req.optString("name", "").trim();
                    if (content.isEmpty()) {
                        sendJson(exchange, 400, new JSONObject().put("status", "error").put("message", "Nội dung trống"));
                        return;
                    }
                    if (name.isEmpty()) {
                        name = content.split("\\R")[0].substring(0, Math.min(content.length(), 25)).trim();
                    }
                    String safeName = name.replaceAll("[\\\\/:*?\"<>|]", "_");
                    if (!safeName.endsWith(".txt")) safeName += ".txt";

                    Path target = messagesDir.resolve(safeName);
                    Files.writeString(target, content, StandardCharsets.UTF_8);
                    appendLog("Đã lưu mẫu tin: " + safeName);
                    sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã lưu mẫu tin: " + safeName).put("name", safeName));
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/api/delete_template", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = new JSONObject(body);
                    String name = req.optString("name", "").trim();
                    String safeName = Paths.get(name).getFileName().toString();
                    if (!safeName.endsWith(".txt")) safeName += ".txt";
                    Path target = messagesDir.resolve(safeName);
                    if (Files.exists(target)) {
                        Files.delete(target);
                        appendLog("Đã xóa mẫu tin: " + safeName);
                        sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã xóa mẫu tin: " + safeName));
                    } else {
                        sendJson(exchange, 404, new JSONObject().put("status", "error").put("message", "Không tìm thấy mẫu tin"));
                    }
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        // 5. Direct Send SMS API
        server.createContext("/api/send_sms", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = new JSONObject(body);
                    String phone = req.optString("phone", "").trim();
                    String message = req.optString("message", "").trim();
                    String name = req.optString("name", "Khách hàng").trim();
                    String deviceId = req.optString("device_id", "AUTO").trim();

                    if (phone.isEmpty() || message.isEmpty()) {
                        sendJson(exchange, 400, new JSONObject().put("status", "error").put("message", "Thiếu số điện thoại hoặc nội dung tin nhắn"));
                        return;
                    }

                    boolean success = executeSendSms(deviceId, phone, message, name);
                    if (success) {
                        sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã gửi tin nhắn tới " + phone));
                    } else {
                        sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", "Lỗi gửi tin nhắn"));
                    }
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        // 6. Conversations & Messages API
        server.createContext("/api/conversations", exchange -> {
            Map<String, HistoryItem> latestByPhone = new LinkedHashMap<>();
            for (int i = historyList.size() - 1; i >= 0; i--) {
                HistoryItem item = historyList.get(i);
                if (!latestByPhone.containsKey(item.phone())) {
                    latestByPhone.put(item.phone(), item);
                }
            }

            JSONArray convList = new JSONArray();
            for (var entry : latestByPhone.entrySet()) {
                HistoryItem h = entry.getValue();
                JSONObject c = new JSONObject();
                c.put("phone", h.phone());
                c.put("name", h.customer_name());
                c.put("last_message", h.message());
                c.put("last_time", h.updated_at());
                c.put("last_status", h.status());
                c.put("last_transport", h.transport());
                c.put("unread", 0);
                convList.put(c);
            }
            sendJson(exchange, new JSONObject().put("conversations", convList));
        });

        server.createContext("/api/messages", exchange -> {
            String query = exchange.getRequestURI().getQuery();
            String phone = "";
            if (query != null) {
                for (String param : query.split("&")) {
                    String[] pair = param.split("=");
                    if (pair.length == 2 && "phone".equals(pair[0])) {
                        phone = URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
                    }
                }
            }

            JSONArray msgList = new JSONArray();
            int idCounter = 1;
            String phoneSuffix = phone.length() > 9 ? phone.substring(phone.length() - 9) : phone;
            for (HistoryItem h : historyList) {
                if (phone.isEmpty() || h.phone().endsWith(phoneSuffix)) {
                    JSONObject m = new JSONObject();
                    m.put("id", idCounter++);
                    m.put("phone", h.phone());
                    m.put("customer_name", h.customer_name());
                    m.put("message", h.message());
                    m.put("status", h.status());
                    m.put("delivery_status", h.delivery_status());
                    m.put("created_at", h.updated_at());
                    m.put("updated_at", h.updated_at());
                    m.put("transport", h.transport());
                    m.put("device_id", h.device_id());
                    m.put("modem_response", h.modem_response());
                    msgList.put(m);
                }
            }
            sendJson(exchange, new JSONObject().put("phone", phone).put("messages", msgList));
        });

        // 7. Campaign Excel Download & Upload APIs
        server.createContext("/api/download_template", exchange -> {
            try {
                byte[] data = getOrCreateSampleExcel();
                exchange.getResponseHeaders().set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
                exchange.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"dulieu_mau.xlsx\"");
                exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
                exchange.sendResponseHeaders(200, data.length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(data);
                }
            } catch (Exception e) {
                sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", "Lỗi tạo file mẫu: " + e.getMessage()));
            }
        });

        server.createContext("/api/download_campaign_excel", exchange -> {
            try {
                Path target = (uploadedExcelPath != null && Files.exists(uploadedExcelPath)) ? uploadedExcelPath : Paths.get("dulieu.xlsx");
                if (target == null || !Files.exists(target)) {
                    sendJson(exchange, 404, new JSONObject().put("status", "no_file").put("message", "Chưa có file chiến dịch"));
                    return;
                }
                byte[] bytes = Files.readAllBytes(target);
                exchange.getResponseHeaders().set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
                exchange.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"dulieu_da_danh_dau.xlsx\"");
                exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
                exchange.sendResponseHeaders(200, bytes.length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(bytes);
                }
            } catch (Exception e) {
                sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", "Lỗi tải file chiến dịch: " + e.getMessage()));
            }
        });

        server.createContext("/api/save_campaign_templates", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = new JSONObject(body);
                    JSONArray arr = req.optJSONArray("templates");
                    if (arr == null || arr.isEmpty()) {
                        sendJson(exchange, 400, new JSONObject().put("status", "error").put("message", "Vui lòng nhập ít nhất 1 nội dung tin nhắn"));
                        return;
                    }
                    Files.createDirectories(messagesDir);
                    for (int i = 0; i < arr.length(); i++) {
                        String t = arr.getString(i).trim();
                        if (!t.isEmpty()) {
                            Path tFile = messagesDir.resolve("mau_tin_" + (i + 1) + ".txt");
                            Files.writeString(tFile, t, StandardCharsets.UTF_8);
                        }
                    }
                    appendLog("Đã lưu " + arr.length() + " mẫu tin nhắn xoay vòng");
                    sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã lưu mẫu tin nhắn thành công!"));
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/api/upload_excel", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    byte[] rawBytes = exchange.getRequestBody().readAllBytes();
                    String contentType = exchange.getRequestHeaders().getFirst("Content-Type");
                    MultipartFile uploaded = parseMultipart(rawBytes, contentType);

                    if (uploaded.data == null || uploaded.data.length == 0) {
                        sendJson(exchange, 400, new JSONObject().put("status", "empty_file").put("message", "File không hợp lệ hoặc dữ liệu trống"));
                        return;
                    }

                    String fname = (uploaded.filename != null ? uploaded.filename : "dulieu.xlsx").toLowerCase(Locale.ROOT);
                    Path tempFile;
                    if (fname.endsWith(".csv") || isCsvContent(uploaded.data)) {
                        tempFile = convertCsvToXlsx(uploaded.data);
                    } else {
                        tempFile = Files.createTempFile("campaign_", ".xlsx");
                        Files.write(tempFile, uploaded.data);
                    }
                    uploadedExcelPath = tempFile;

                    try {
                        Files.copy(tempFile, Paths.get("dulieu.xlsx"), StandardCopyOption.REPLACE_EXISTING);
                    } catch (Exception ignored) {}

                    JSONObject info = parseExcelSheet(tempFile, uploaded.filename);
                    campaignInfoCache = info;
                    appendLog("📥 Tải lên Excel thành công (" + uploaded.filename + "): " + info.optInt("total_valid") + " SĐT hợp lệ");
                    sendJson(exchange, info);
                    return;
                } catch (Exception e) {
                    appendLog("❌ Lỗi tải lên Excel: " + e.getMessage());
                    sendJson(exchange, 400, new JSONObject().put("status", "error").put("message", "Lỗi đọc file: " + e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/api/reset_campaign_status", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    Path target = (uploadedExcelPath != null && Files.exists(uploadedExcelPath)) ? uploadedExcelPath : Paths.get("dulieu.xlsx");
                    if (target == null || !Files.exists(target)) {
                        sendJson(exchange, 404, new JSONObject().put("status", "no_file").put("message", "Chưa có file dữ liệu"));
                        return;
                    }
                    try (InputStream is = Files.newInputStream(target); Workbook wb = WorkbookFactory.create(is)) {
                        Sheet sheet = wb.getSheetAt(0);
                        Row header = sheet.getRow(0);
                        if (header != null) {
                            int successCol = -1;
                            int successAtCol = -1;
                            for (Cell c : header) {
                                String v = CampaignService.text(c).trim().toUpperCase(Locale.ROOT);
                                if (v.equals(CampaignService.SUCCESS) || v.equals("ĐÃ GỬI") || v.equals("DA GUI")) successCol = c.getColumnIndex();
                                if (v.equals(CampaignService.SUCCESS_AT) || v.contains("THỜI GIAN GỬI")) successAtCol = c.getColumnIndex();
                            }
                            if (successCol >= 0 || successAtCol >= 0) {
                                for (int i = 1; i <= sheet.getLastRowNum(); i++) {
                                    Row r = sheet.getRow(i);
                                    if (r != null) {
                                        if (successCol >= 0) {
                                            Cell c = r.getCell(successCol);
                                            if (c != null) c.setCellValue("");
                                        }
                                        if (successAtCol >= 0) {
                                            Cell c = r.getCell(successAtCol);
                                            if (c != null) c.setCellValue("");
                                        }
                                    }
                                }
                                Path temp = target.resolveSibling(target.getFileName() + ".tmp.xlsx");
                                try (OutputStream os = Files.newOutputStream(temp)) {
                                    wb.write(os);
                                }
                                Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
                                try {
                                    Path rootDulieu = Paths.get("dulieu.xlsx");
                                    if (!Files.isSameFile(target, rootDulieu)) {
                                        Files.copy(target, rootDulieu, StandardCopyOption.REPLACE_EXISTING);
                                    }
                                } catch (Exception ignored) {}
                            }
                        }
                    }
                    campaignInfoCache = parseExcelSheet(target, target.getFileName().toString());
                    appendLog("🔄 Đã xóa toàn bộ trạng thái đã gửi trong file Excel. Sẵn sàng gửi lại!");
                    sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã xóa trạng thái đã gửi, sẵn sàng gửi lại toàn bộ"));
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", "Lỗi reset trạng thái: " + e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/api/campaign_info", exchange -> {
            try {
                Path candidate = (uploadedExcelPath != null && Files.exists(uploadedExcelPath)) ? uploadedExcelPath : Paths.get("dulieu.xlsx");
                if (Files.exists(candidate)) {
                    campaignInfoCache = parseExcelSheet(candidate, candidate.getFileName().toString());
                    uploadedExcelPath = candidate;
                }
                JSONObject info = new JSONObject(campaignInfoCache.toString());
                if (!info.has("has_excel")) info.put("has_excel", Files.exists(candidate));
                if (!info.has("filename")) info.put("filename", candidate.getFileName().toString());
                if (!info.has("total_valid")) info.put("total_valid", 0);
                if (!info.has("total_invalid")) info.put("total_invalid", 0);
                if (!info.has("preview")) info.put("preview", new JSONArray());
                info.put("templates", loadCampaignTemplates());
                sendJson(exchange, info);
            } catch (Exception e) {
                sendJson(exchange, new JSONObject().put("has_excel", false).put("templates", loadCampaignTemplates()));
            }
        });

        // 8. Campaign Start & Stop API
        server.createContext("/start", exchange -> {
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = body.isBlank() ? new JSONObject() : new JSONObject(body);

                    if (uploadedExcelPath == null || !Files.exists(uploadedExcelPath)) {
                        Path local = Paths.get("dulieu.xlsx");
                        if (Files.exists(local)) {
                            uploadedExcelPath = local;
                        } else {
                            sendJson(exchange, 400, new JSONObject().put("status", "error").put("message", "Vui lòng chọn hoặc tải file Excel lên trước"));
                            return;
                        }
                    }

                    int delay = req.optInt("delay", 0);
                    if (delay <= 0) delay = (int) req.optDouble("delay_min", 5);
                    if (delay <= 0) delay = 5;

                    String serial = req.optString("device_id", "AUTO");

                    List<String> tpls = new ArrayList<>();
                    JSONArray tplArr = req.optJSONArray("templates");
                    if (tplArr != null && tplArr.length() > 0) {
                        for (int i = 0; i < tplArr.length(); i++) {
                            String t = tplArr.getString(i).trim();
                            if (!t.isEmpty()) tpls.add(t);
                        }
                    }
                    if (tpls.isEmpty()) {
                        JSONArray diskTpls = loadCampaignTemplates();
                        for (int i = 0; i < diskTpls.length(); i++) {
                            String c = diskTpls.getJSONObject(i).optString("content", "").trim();
                            if (!c.isEmpty()) tpls.add(c);
                        }
                    }
                    if (tpls.isEmpty()) {
                        tpls.add("Xin chào {name}, chúc bạn một ngày tốt lành!");
                    }

                    JSONObject sheetInfo = parseExcelSheet(uploadedExcelPath, uploadedExcelPath.getFileName().toString());
                    int totalToSend = sheetInfo.optInt("total_valid", 0);
                    if (totalToSend <= 0) {
                        sendJson(exchange, 409, new JSONObject()
                            .put("status", "all_sent")
                            .put("message", "Tất cả " + sheetInfo.optInt("total_sent_success", 0) + " khách hàng đã gửi thành công trước đó. Không gửi lại."));
                        return;
                    }

                    // Phân bổ và chia kênh gửi cho nhiều điện thoại và nhiều SIM
                    List<CampaignService.TargetChannel> channels = new ArrayList<>();
                    if ("AUTO".equals(serial) || "ALL".equals(serial)) {
                        for (String d : adb.devices()) {
                            List<Integer> subs = adb.getActiveSubscriptions(d);
                            for (int sub : subs) {
                                String lbl = "ADB:" + d + (sub >= 0 ? " [SIM " + sub + "]" : "");
                                channels.add(new CampaignService.TargetChannel(d, sub, lbl));
                            }
                        }
                        for (JSONObject cd : getActiveCloudDevices()) {
                            String cid = cd.optString("id", "android-01");
                            JSONArray sims = cd.optJSONArray("sims");
                            List<Integer> csubs = new ArrayList<>();
                            if (sims != null) {
                                for (int s = 0; s < sims.length(); s++) {
                                    JSONObject simObj = sims.getJSONObject(s);
                                    if (simObj.optBoolean("in_service", true)) {
                                        int subId = simObj.optInt("subscription_id", -1);
                                        if (subId >= 0) csubs.add(subId);
                                    }
                                }
                            }
                            if (csubs.isEmpty()) csubs.add(-1);
                            for (int sub : csubs) {
                                String lbl = "Wi-Fi:" + cid + (sub >= 0 ? " [SIM " + sub + "]" : "");
                                channels.add(new CampaignService.TargetChannel("cloud:" + cid, sub, lbl));
                            }
                        }
                    } else {
                        if (serial.startsWith("cloud:")) {
                            String cid = serial.substring(6);
                            JSONObject cd = cloudDevices.get(cid);
                            JSONArray sims = cd != null ? cd.optJSONArray("sims") : null;
                            List<Integer> csubs = new ArrayList<>();
                            if (sims != null) {
                                for (int s = 0; s < sims.length(); s++) {
                                    JSONObject simObj = sims.getJSONObject(s);
                                    if (simObj.optBoolean("in_service", true)) {
                                        int subId = simObj.optInt("subscription_id", -1);
                                        if (subId >= 0) csubs.add(subId);
                                    }
                                }
                            }
                            if (csubs.isEmpty()) csubs.add(-1);
                            for (int sub : csubs) {
                                String lbl = "Wi-Fi:" + cid + (sub >= 0 ? " [SIM " + sub + "]" : "");
                                channels.add(new CampaignService.TargetChannel(serial, sub, lbl));
                            }
                        } else {
                            List<Integer> subs = adb.getActiveSubscriptions(serial);
                            for (int sub : subs) {
                                String lbl = "ADB:" + serial + (sub >= 0 ? " [SIM " + sub + "]" : "");
                                channels.add(new CampaignService.TargetChannel(serial, sub, lbl));
                            }
                        }
                    }

                    if (channels.isEmpty()) {
                        channels.add(new CampaignService.TargetChannel("AUTO", -1, "Android"));
                    }

                    final List<CampaignService.TargetChannel> finalChannels = channels;
                    final int delaySec = delay;
                    final List<String> finalTpls = tpls;
                    final Path targetExcel = uploadedExcelPath;

                    new Thread(() -> {
                        campaign.run(targetExcel, finalChannels, finalTpls, delaySec, SmsSenderDesktop::appendLog);
                    }, "CampaignWorker").start();

                    appendLog("🚀 Bắt đầu chiến dịch: " + totalToSend + " khách hàng | " + channels.size() + " kênh gửi (điện thoại/SIM)");
                    sendJson(exchange, new JSONObject()
                        .put("status", "ok")
                        .put("message", "Đã bắt đầu chiến dịch")
                        .put("total", totalToSend)
                        .put("channels_count", channels.size())
                        .put("templates_count", tpls.size()));
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 405, "text/plain", "Method Not Allowed".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/stop", exchange -> {
            campaign.stop();
            appendLog("Đã tạm dừng chiến dịch gửi tin");
            sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã dừng chiến dịch"));
        });

        // 9. History Table & Android Events Table
        server.createContext("/history", exchange -> {
            JSONArray rows = new JSONArray();
            for (int i = historyList.size() - 1; i >= 0; i--) {
                HistoryItem h = historyList.get(i);
                JSONObject r = new JSONObject();
                r.put("updated_at", h.updated_at());
                r.put("phone", h.phone());
                r.put("customer_name", h.customer_name());
                r.put("transport", h.transport());
                r.put("device_id", h.device_id());
                r.put("message_ref", h.message_ref());
                r.put("status", h.status());
                r.put("delivery_status", h.delivery_status());
                r.put("message", h.message());
                r.put("modem_response", h.modem_response());
                rows.put(r);
            }
            sendJson(exchange, new JSONObject().put("rows", rows));
        });

        server.createContext("/android-events", exchange -> {
            sendJson(exchange, new JSONObject().put("rows", new JSONArray(androidEvents)));
        });

        // 10. Network Info API
        server.createContext("/api/network_info", exchange -> {
            String lanIp = getLanIpAddress();
            String masterUrl = "http://" + lanIp + ":" + activePort;
            String downloadUrl = "http://" + lanIp + ":" + activePort + "/download/apk";
            JSONObject obj = new JSONObject();
            obj.put("master_lan_ip", lanIp);
            obj.put("primary_ip", lanIp);
            obj.put("server_port", activePort);
            obj.put("master_lan_url", masterUrl);
            obj.put("master_web_url", masterUrl);
            obj.put("download_url", downloadUrl);
            sendJson(exchange, obj);
        });

        // 11. Zalo Multi-profile Launcher
        server.createContext("/api/zalo/open", exchange -> {
            try {
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                JSONObject req = new JSONObject(body);
                int slot = req.optInt("slot", 1);
                zalo.open(slot);
                appendLog("Đã mở Zalo phiên đăng nhập slot " + slot);
                sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã mở Zalo " + slot));
            } catch (Exception e) {
                sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
            }
        });

        server.createContext("/api/zalo/reset", exchange -> {
            try {
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                JSONObject req = new JSONObject(body);
                int slot = req.optInt("slot", 1);
                zalo.reset(slot);
                appendLog("Đã reset dữ liệu Zalo slot " + slot);
                sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đã reset Zalo " + slot));
            } catch (Exception e) {
                sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
            }
        });

        // 12. Shutdown API
        server.createContext("/shutdown", exchange -> {
            sendJson(exchange, new JSONObject().put("status", "ok").put("message", "Đang tắt ứng dụng"));
            new Thread(() -> {
                try { Thread.sleep(500); } catch (Exception ignored) {}
                System.exit(0);
            }).start();
        });

        // 13. Cloud Companion Sync APIs
        server.createContext("/v1/device/jobs/next", exchange -> {
            String deviceId = exchange.getRequestHeaders().getFirst("X-Device-Id");
            if (deviceId == null || deviceId.isBlank()) deviceId = "android-01";
            deviceId = deviceId.trim();
            String remoteIp = exchange.getRemoteAddress() != null && exchange.getRemoteAddress().getAddress() != null 
                ? exchange.getRemoteAddress().getAddress().getHostAddress() : "";
            
            JSONObject dev = cloudDevices.getOrDefault(deviceId, new JSONObject());
            dev.put("id", deviceId);
            dev.put("ip", remoteIp);
            dev.put("last_seen", System.currentTimeMillis());
            String simsHdr = exchange.getRequestHeaders().getFirst("X-Device-Sims");
            if (simsHdr != null && !simsHdr.isBlank()) {
                try {
                    dev.put("sims", new JSONArray(simsHdr.trim()));
                } catch (Exception ignored) {}
            }
            cloudDevices.put(deviceId, dev);

            JSONObject job = null;
            var queue = cloudJobs.get(deviceId);
            if (queue != null && !queue.isEmpty()) {
                job = queue.remove(0);
            } else {
                var anyQueue = cloudJobs.get("__any__");
                if (anyQueue != null && !anyQueue.isEmpty()) {
                    job = anyQueue.remove(0);
                }
            }

            if (job != null) {
                sendJson(exchange, 200, job);
            } else {
                sendResponse(exchange, 204, "text/plain", new byte[0]);
            }
        });

        server.createContext("/v1/device/jobs/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            if ("POST".equalsIgnoreCase(exchange.getRequestMethod()) && path.endsWith("/result")) {
                String[] parts = path.split("/");
                String jobId = parts.length >= 5 ? parts[4] : "";
                String deviceId = exchange.getRequestHeaders().getFirst("X-Device-Id");
                if (deviceId == null || deviceId.isBlank()) deviceId = "android-01";
                deviceId = deviceId.trim();
                String remoteIp = exchange.getRemoteAddress() != null && exchange.getRemoteAddress().getAddress() != null 
                    ? exchange.getRemoteAddress().getAddress().getHostAddress() : "";

                JSONObject dev = cloudDevices.getOrDefault(deviceId, new JSONObject());
                dev.put("id", deviceId);
                dev.put("ip", remoteIp);
                dev.put("last_seen", System.currentTimeMillis());
                String simsHdr = exchange.getRequestHeaders().getFirst("X-Device-Sims");
                if (simsHdr != null && !simsHdr.isBlank()) {
                    try {
                        dev.put("sims", new JSONArray(simsHdr.trim()));
                    } catch (Exception ignored) {}
                }
                cloudDevices.put(deviceId, dev);

                try {
                    String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                    JSONObject req = body.isBlank() ? new JSONObject() : new JSONObject(body);
                    String status = req.optString("status", "").toUpperCase(Locale.ROOT);
                    String detail = req.optString("detail", "");
                    String phone = req.optString("phone", "");
                    String message = req.optString("message", "");
                    int subId = req.optInt("subscription_id", -1);

                    String historyStatus;
                    String deliveryStatus;
                    if ("QUEUED".equals(status)) {
                        historyStatus = "ANDROID_QUEUED";
                        deliveryStatus = "Đang gửi từ điện thoại...";
                    } else if ("DELIVERED".equals(status)) {
                        historyStatus = "DELIVERED";
                        deliveryStatus = "Đã giao đến người nhận";
                    } else if ("SENT".equals(status)) {
                        historyStatus = "SENT";
                        deliveryStatus = "Đã gửi qua SIM thành công";
                    } else if ("FAILED".equals(status)) {
                        historyStatus = "FAILED";
                        deliveryStatus = detail.isEmpty() ? "Lỗi gửi SMS" : detail;
                    } else {
                        historyStatus = status;
                        deliveryStatus = detail.isEmpty() ? status : detail;
                    }

                    if ("SENT".equals(historyStatus) || "DELIVERED".equals(historyStatus)) {
                        var future = pendingJobFutures.remove(jobId);
                        if (future != null) {
                            future.complete(true);
                        }
                    } else if ("FAILED".equals(historyStatus)) {
                        var future = pendingJobFutures.remove(jobId);
                        if (future != null) {
                            future.complete(false);
                        }
                    }

                    boolean updated = false;
                    for (int i = 0; i < historyList.size(); i++) {
                        HistoryItem h = historyList.get(i);
                        if (jobId.equals(h.message_ref())) {
                            historyList.set(i, new HistoryItem(
                                LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),
                                h.phone(),
                                h.customer_name(),
                                h.transport(),
                                h.device_id(),
                                h.message_ref(),
                                historyStatus,
                                deliveryStatus,
                                h.message(),
                                detail
                            ));
                            updated = true;
                            break;
                        }
                    }
                    if (!updated && !phone.isEmpty()) {
                        historyList.add(new HistoryItem(
                            LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),
                            phone,
                            "Khách hàng",
                            "ANDROID",
                            "cloud:" + deviceId,
                            jobId,
                            historyStatus,
                            deliveryStatus,
                            message,
                            detail
                        ));
                    }

                    String simSuffix = subId >= 0 ? " [SIM " + subId + "]" : "";
                    JSONObject ev = new JSONObject();
                    ev.put("device_id", "cloud:" + deviceId);
                    ev.put("model", "Wi-Fi App: " + deviceId + simSuffix);
                    ev.put("job_id", jobId);
                    ev.put("subscription_id", subId);
                    ev.put("status", ("SENT".equals(historyStatus) || "DELIVERED".equals(historyStatus)) ? "SUCCESS" : ("ANDROID_QUEUED".equals(historyStatus) ? "PENDING" : "FAILED"));
                    ev.put("latest_stage", status);
                    ev.put("error", "FAILED".equals(historyStatus) ? detail : "");
                    ev.put("response", detail.isEmpty() ? deliveryStatus : detail);
                    androidEvents.add(ev);
                    if (androidEvents.size() > 200) androidEvents.remove(0);

                    if ("SENT".equals(historyStatus) || "DELIVERED".equals(historyStatus)) {
                        appendLog("✅ Máy Android " + deviceId + simSuffix + ": " + deliveryStatus + " (" + (jobId.length() > 8 ? jobId.substring(0, 8) : jobId) + ")");
                    } else if ("FAILED".equals(historyStatus)) {
                        appendLog("❌ Máy Android " + deviceId + simSuffix + " báo lỗi: " + (detail.isEmpty() ? "Thất bại" : detail));
                    } else if ("ANDROID_QUEUED".equals(historyStatus)) {
                        appendLog("ℹ️ Máy Android " + deviceId + simSuffix + " đã nhận lệnh gửi: " + (jobId.length() > 8 ? jobId.substring(0, 8) : jobId));
                    }

                    sendJson(exchange, new JSONObject().put("status", "ok"));
                    return;
                } catch (Exception e) {
                    sendJson(exchange, 500, new JSONObject().put("status", "error").put("message", e.getMessage()));
                    return;
                }
            }
            sendResponse(exchange, 404, "text/plain", "Not Found".getBytes(StandardCharsets.UTF_8));
        });

        server.createContext("/v1/devices", exchange -> {
            JSONArray arr = new JSONArray();
            for (var d : getActiveCloudDevices()) {
                arr.put(d);
            }
            sendJson(exchange, new JSONObject().put("devices", arr));
        });

        server.createContext("/health", exchange -> {
            sendJson(exchange, new JSONObject().put("status", "ok").put("time", LocalDateTime.now().toString()));
        });
    }

    private static void startUdpDiscoveryResponder() {
        new Thread(() -> {
            try (DatagramSocket socket = new DatagramSocket(8766)) {
                socket.setReuseAddress(true);
                byte[] buf = new byte[1024];
                while (true) {
                    DatagramPacket packet = new DatagramPacket(buf, buf.length);
                    socket.receive(packet);
                    String msg = new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8);
                    if (msg.contains("DISCOVER_SMS_MASTER")) {
                        String lanIp = getLanIpAddress();
                        JSONObject resp = new JSONObject();
                        resp.put("service", "SMS_BRIDGE_MASTER");
                        resp.put("ip", lanIp);
                        resp.put("lan_port", activePort);
                        resp.put("web_port", activePort);
                        resp.put("lan_url", "http://" + lanIp + ":" + activePort);
                        resp.put("web_url", "http://" + lanIp + ":" + activePort);
                        byte[] data = resp.toString().getBytes(StandardCharsets.UTF_8);
                        socket.send(new DatagramPacket(data, data.length, packet.getAddress(), packet.getPort()));
                    }
                }
            } catch (Exception ignored) {
                // Port 8766 may be in use by Python or another instance
            }
        }, "UdpDiscoveryResponder").start();
    }

    private static byte[] loadWebIndexHtml() {
        try (InputStream in = SmsSenderDesktop.class.getResourceAsStream("/web/index.html")) {
            if (in != null) return in.readAllBytes();
        } catch (Exception ignored) {}

        // Fallback: check filesystem templates/index.html
        try {
            Path p = Paths.get("templates", "index.html");
            if (Files.exists(p)) return Files.readAllBytes(p);
        } catch (Exception ignored) {}

        return "<html><body><h1>SMS Sender Tool (Standalone Java)</h1><p>Vui lòng kiểm tra file giao diện index.html</p></body></html>"
            .getBytes(StandardCharsets.UTF_8);
    }

    public static boolean executeSendSms(String deviceId, String phone, String message, String name) {
        return executeSendSms(new CampaignService.TargetChannel(deviceId, -1, deviceId), phone, message, name);
    }

    public static boolean executeSendSms(CampaignService.TargetChannel channel, String phone, String message, String name) {
        String deviceId = channel.deviceId();
        int subscriptionId = channel.subscriptionId();
        String label = channel.label();
        try {
            boolean isCloud = deviceId.startsWith("cloud:") || cloudDevices.containsKey(deviceId) ||
                ("AUTO".equals(deviceId) && adb.listDevices().isEmpty() && !getActiveCloudDevices().isEmpty());

            if (isCloud) {
                String targetId = deviceId.startsWith("cloud:") ? deviceId.substring(6) : (
                    "AUTO".equals(deviceId) ? getActiveCloudDevices().get(0).optString("id", "android-01") : deviceId
                );
                String jobId = UUID.randomUUID().toString().replace("-", "");
                CompletableFuture<Boolean> future = new CompletableFuture<>();
                pendingJobFutures.put(jobId, future);

                JSONObject job = new JSONObject();
                job.put("id", jobId);
                job.put("device_id", targetId);
                job.put("phone", phone);
                job.put("message", message);
                job.put("subscription_id", subscriptionId);
                job.put("created_at", System.currentTimeMillis());

                cloudJobs.computeIfAbsent(targetId, k -> new CopyOnWriteArrayList<>()).add(job);

                String timeStr = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
                historyList.add(new HistoryItem(
                    timeStr, phone, name, "ANDROID", label,
                    jobId,
                    "ANDROID_QUEUED",
                    "Đang gửi từ điện thoại...",
                    message,
                    "Đã đưa tin nhắn vào hàng đợi Wi-Fi App (" + label + ")"
                ));

                appendLog("⏳ ĐANG GỬI [" + label + "] " + phone + "...");

                boolean success = false;
                try {
                    success = future.get(22, TimeUnit.SECONDS);
                } catch (TimeoutException te) {
                    appendLog("❌ HẾT HẠN CHỜ [" + label + "] " + phone + ": Không nhận được xác nhận từ điện thoại/nhà mạng");
                    pendingJobFutures.remove(jobId);
                } catch (Exception ex) {
                    appendLog("❌ LỖI [" + label + "] " + phone + ": " + ex.getMessage());
                    pendingJobFutures.remove(jobId);
                }
                return success;
            }

            String jobId = UUID.randomUUID().toString();
            AdbClient.CommandResult result = adb.send(deviceId, phone, message, subscriptionId, jobId);
            if (!result.successful()) {
                appendLog("❌ GỬI LỖI ADB [" + label + "] " + phone + ": " + result.output());
                return false;
            }

            appendLog("⏳ ĐANG GỬI ADB [" + label + "] " + phone + "...");
            String status = adb.checkJobStatus(deviceId, jobId, 15);
            boolean success = "SUCCESS".equals(status);
            String timeStr = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));

            historyList.add(new HistoryItem(
                timeStr, phone, name, "ANDROID", label,
                jobId.substring(0, 8),
                success ? "SENT" : "FAILED",
                success ? "Đã gửi qua SIM thành công" : ("Lỗi: " + status),
                message,
                result.output()
            ));

            if (success) {
                appendLog("✅ ĐÃ GỬI THÀNH CÔNG [" + label + "] " + phone);
            } else {
                appendLog("❌ NHÀ MẠNG BÁO LỖI [" + label + "] " + phone + ": " + status);
            }
            return success;
        } catch (Exception e) {
            appendLog("❌ Lỗi gửi tin tới " + phone + ": " + e.getMessage());
            return false;
        }
    }

    public static class MultipartFile {
        public String filename = "dulieu.xlsx";
        public byte[] data = new byte[0];
    }

    private static boolean isCsvContent(byte[] data) {
        if (data == null || data.length < 4) return false;
        if (data[0] == 0x50 && data[1] == 0x4B && data[2] == 0x03 && data[3] == 0x04) return false;
        if ((data[0] & 0xFF) == 0xD0 && (data[1] & 0xFF) == 0xCF && (data[2] & 0xFF) == 0x11 && (data[3] & 0xFF) == 0xE0) return false;
        return true;
    }

    private static MultipartFile parseMultipart(byte[] body, String headerContentType) {
        MultipartFile result = new MultipartFile();
        if (body == null || body.length == 0) return result;

        String boundary = null;
        if (headerContentType != null && headerContentType.toLowerCase(Locale.ROOT).contains("boundary=")) {
            int bIdx = headerContentType.toLowerCase(Locale.ROOT).indexOf("boundary=");
            String b = headerContentType.substring(bIdx + 9).trim();
            int semi = b.indexOf(';');
            if (semi >= 0) b = b.substring(0, semi).trim();
            if (b.startsWith("\"") && b.endsWith("\"") && b.length() >= 2) {
                b = b.substring(1, b.length() - 1);
            }
            boundary = b;
        }

        if (boundary == null || boundary.isEmpty()) {
            if (body.length > 2 && body[0] == '-' && body[1] == '-') {
                int lineEnd = indexOfBytes(body, new byte[]{'\r', '\n'}, 0);
                if (lineEnd < 0) lineEnd = indexOfBytes(body, new byte[]{'\n'}, 0);
                if (lineEnd > 2) {
                    boundary = new String(body, 2, lineEnd - 2, StandardCharsets.ISO_8859_1).trim();
                }
            }
        }

        if (boundary != null && !boundary.isEmpty()) {
            byte[] boundBytes = ("--" + boundary).getBytes(StandardCharsets.ISO_8859_1);
            int firstBound = indexOfBytes(body, boundBytes, 0);
            if (firstBound >= 0) {
                int partHeaderStart = firstBound + boundBytes.length;
                if (partHeaderStart < body.length && body[partHeaderStart] == '\r') partHeaderStart++;
                if (partHeaderStart < body.length && body[partHeaderStart] == '\n') partHeaderStart++;

                int partBodyStart = -1;
                byte[] crlfcrlf = "\r\n\r\n".getBytes(StandardCharsets.ISO_8859_1);
                byte[] lflf = "\n\n".getBytes(StandardCharsets.ISO_8859_1);
                int sepIdx = indexOfBytes(body, crlfcrlf, partHeaderStart);
                int sepLen = 4;
                if (sepIdx < 0) {
                    sepIdx = indexOfBytes(body, lflf, partHeaderStart);
                    sepLen = 2;
                }
                if (sepIdx >= 0) {
                    partBodyStart = sepIdx + sepLen;
                    String partHeaderStr = new String(body, partHeaderStart, sepIdx - partHeaderStart, StandardCharsets.UTF_8);

                    java.util.regex.Matcher m = java.util.regex.Pattern.compile("filename=\"?([^\";\\r\\n]+)\"?").matcher(partHeaderStr);
                    if (m.find()) {
                        result.filename = m.group(1).trim();
                    }

                    int partEnd = indexOfBytes(body, boundBytes, partBodyStart);
                    if (partEnd < 0) {
                        partEnd = body.length;
                    } else {
                        if (partEnd >= 2 && body[partEnd - 2] == '\r' && body[partEnd - 1] == '\n') {
                            partEnd -= 2;
                        } else if (partEnd >= 1 && body[partEnd - 1] == '\n') {
                            partEnd -= 1;
                        }
                    }

                    if (partEnd > partBodyStart) {
                        byte[] partData = Arrays.copyOfRange(body, partBodyStart, partEnd);
                        byte[] pkMagic = new byte[]{0x50, 0x4B, 0x03, 0x04};
                        int pkIdx = indexOfBytes(partData, pkMagic, 0);
                        if (pkIdx > 0 && pkIdx < 128) {
                            partData = Arrays.copyOfRange(partData, pkIdx, partData.length);
                        }
                        result.data = partData;
                        return result;
                    }
                }
            }
        }

        byte[] pkMagic = new byte[]{0x50, 0x4B, 0x03, 0x04};
        int pkIdx = indexOfBytes(body, pkMagic, 0);
        if (pkIdx >= 0) {
            int end = body.length;
            if (boundary != null) {
                byte[] boundBytes = ("--" + boundary).getBytes(StandardCharsets.ISO_8859_1);
                int bEnd = indexOfBytes(body, boundBytes, pkIdx);
                if (bEnd > pkIdx) {
                    end = bEnd;
                    if (end >= 2 && body[end - 2] == '\r' && body[end - 1] == '\n') end -= 2;
                    else if (end >= 1 && body[end - 1] == '\n') end -= 1;
                }
            }
            result.data = Arrays.copyOfRange(body, pkIdx, end);
            return result;
        }

        result.data = body;
        return result;
    }

    private static Path convertCsvToXlsx(byte[] csvBytes) throws IOException {
        String content = new String(csvBytes, StandardCharsets.UTF_8);
        if (content.contains("\uFFFD")) {
            content = new String(csvBytes, StandardCharsets.ISO_8859_1);
        }

        try (org.apache.poi.xssf.usermodel.XSSFWorkbook wb = new org.apache.poi.xssf.usermodel.XSSFWorkbook()) {
            org.apache.poi.ss.usermodel.Sheet sheet = wb.createSheet("Sheet1");
            String[] lines = content.split("\\r?\\n");
            int rowIdx = 0;
            for (String line : lines) {
                if (line.trim().isEmpty()) continue;
                org.apache.poi.ss.usermodel.Row r = sheet.createRow(rowIdx++);
                List<String> cols = parseCsvLine(line);
                for (int ci = 0; ci < cols.size(); ci++) {
                    r.createCell(ci).setCellValue(cols.get(ci));
                }
            }
            Path temp = Files.createTempFile("campaign_csv_", ".xlsx");
            try (OutputStream os = Files.newOutputStream(temp)) {
                wb.write(os);
            }
            return temp;
        }
    }

    private static List<String> parseCsvLine(String line) {
        List<String> result = new ArrayList<>();
        char sep = ',';
        if (!line.contains(",") && line.contains(";")) sep = ';';
        else if (!line.contains(",") && line.contains("\t")) sep = '\t';

        StringBuilder sb = new StringBuilder();
        boolean inQuotes = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') {
                inQuotes = !inQuotes;
            } else if (c == sep && !inQuotes) {
                result.add(sb.toString().trim());
                sb.setLength(0);
            } else {
                sb.append(c);
            }
        }
        result.add(sb.toString().trim());
        return result;
    }

    private static byte[] getOrCreateSampleExcel() throws IOException {
        Path samplePath = Paths.get("dulieu_mau.xlsx");
        if (Files.exists(samplePath)) {
            return Files.readAllBytes(samplePath);
        }
        try (org.apache.poi.xssf.usermodel.XSSFWorkbook wb = new org.apache.poi.xssf.usermodel.XSSFWorkbook()) {
            org.apache.poi.ss.usermodel.Sheet sheet = wb.createSheet("KhachHang");
            org.apache.poi.ss.usermodel.Row header = sheet.createRow(0);
            header.createCell(0).setCellValue("ĐIỆN THOẠI");
            header.createCell(1).setCellValue("HỌ TÊN");
            header.createCell(2).setCellValue("GIỚI TÍNH");
            header.createCell(3).setCellValue("GHI CHÚ");

            Object[][] rows = {
                {"0912345678", "Nguyễn Văn Tuấn", 1, "1 là Nam (Anh)"},
                {"0987654321", "Trần Thị Mai", 0, "0 là Nữ (Chị)"},
                {"0903112233", "Lê Hoàng Long", 1, "1 là Nam (Anh)"},
                {"0934556677", "Phạm Thu Hà", 0, "0 là Nữ (Chị)"},
                {"0978990011", "Vũ Đức Anh", 1, "1 là Nam (Anh)"}
            };

            for (int i = 0; i < rows.length; i++) {
                org.apache.poi.ss.usermodel.Row r = sheet.createRow(i + 1);
                r.createCell(0).setCellValue((String) rows[i][0]);
                r.createCell(1).setCellValue((String) rows[i][1]);
                r.createCell(2).setCellValue((Integer) rows[i][2]);
                r.createCell(3).setCellValue((String) rows[i][3]);
            }

            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            wb.write(baos);
            byte[] bytes = baos.toByteArray();
            try {
                Files.write(samplePath, bytes);
            } catch (Exception ignored) {}
            return bytes;
        }
    }

    private static JSONArray loadCampaignTemplates() {
        JSONArray arr = new JSONArray();
        if (Files.isDirectory(messagesDir)) {
            try (var stream = Files.list(messagesDir)) {
                stream.filter(p -> p.toString().endsWith(".txt")).sorted().forEach(p -> {
                    try {
                        String c = Files.readString(p, StandardCharsets.UTF_8).trim();
                        if (!c.isEmpty()) {
                            arr.put(new JSONObject().put("name", p.getFileName().toString()).put("content", c));
                        }
                    } catch (Exception ignored) {}
                });
            } catch (Exception ignored) {}
        }
        if (arr.isEmpty()) {
            arr.put(new JSONObject().put("name", "mau_tin_1.txt").put("content", "Xin chào {name}, chúc bạn một ngày tốt lành!"));
            arr.put(new JSONObject().put("name", "mau_tin_2.txt").put("content", "Chào {xungho} {ten}, bên em đang có ưu đãi đặc biệt dành riêng cho {xungho} ạ!"));
        }
        return arr;
    }

    private static JSONObject parseExcelSheet(Path file, String displayFilename) throws Exception {
        JSONObject result = new JSONObject();
        try (InputStream in = Files.newInputStream(file); Workbook wb = WorkbookFactory.create(in)) {
            Sheet sheet = wb.getSheetAt(0);
            Row header = sheet.getRow(0);
            if (header == null) throw new IOException("File Excel không có hàng tiêu đề");

            JSONArray cols = new JSONArray();
            int lastCol = header.getLastCellNum();
            for (int i = 0; i < lastCol; i++) {
                Cell c = header.getCell(i);
                cols.put(c != null ? CampaignService.text(c) : ("Col" + (i + 1)));
            }

            int phoneCol = -1;
            int nameCol = -1;
            int genderCol = -1;
            int sentCol = -1;

            for (int i = 0; i < lastCol; i++) {
                Cell c = header.getCell(i);
                if (c == null) continue;
                String val = CampaignService.text(c).trim().toUpperCase(Locale.ROOT);
                if (phoneCol < 0 && (val.equals("ĐT") || val.equals("ĐIỆN THOẠI") || val.equals("DIEN THOAI") ||
                    val.equals("SDT") || val.equals("SĐT") || val.equals("SO DIEN THOAI") || val.equals("SỐ ĐIỆN THOẠI") ||
                    val.equals("PHONE") || val.equals("TEL") || val.equals("MOBILE") || val.equals("SO_DIEN_THOAI"))) {
                    phoneCol = i;
                }
                if (nameCol < 0 && (val.equals("TÊN") || val.equals("TEN") || val.equals("NAME") ||
                    val.equals("HỌ TÊN") || val.equals("HO TEN") || val.equals("HỌ VÀ TÊN") || val.equals("HO VA TEN") ||
                    val.equals("HOTEN") || val.equals("KHACH HANG") || val.equals("KHÁCH HÀNG") || val.equals("CUSTOMER"))) {
                    nameCol = i;
                }
                if (genderCol < 0 && (val.equals("GIỚI TÍNH") || val.equals("GIOI TINH") || val.equals("GENDER") ||
                    val.equals("SEX") || val.equals("PHÁI") || val.equals("PHAI") || val.equals("XƯNG HÔ") || val.equals("XUNG HO"))) {
                    genderCol = i;
                }
                if (sentCol < 0 && (val.contains("ĐÃ GỬI") || val.contains("STATUS") || val.contains("TRẠNG THÁI"))) {
                    sentCol = i;
                }
            }

            if (phoneCol < 0) {
                for (int i = 0; i < lastCol; i++) {
                    Cell c = header.getCell(i);
                    if (c == null) continue;
                    String val = CampaignService.text(c).trim().toLowerCase(Locale.ROOT);
                    if (val.contains("phone") || val.contains("sdt") || val.contains("điện thoại") || val.contains("dien thoai") || val.contains("đt")) {
                        phoneCol = i;
                        break;
                    }
                }
            }
            if (phoneCol < 0 && lastCol > 0) phoneCol = 0;

            if (nameCol < 0) {
                for (int i = 0; i < lastCol; i++) {
                    Cell c = header.getCell(i);
                    if (c == null) continue;
                    String val = CampaignService.text(c).trim().toLowerCase(Locale.ROOT);
                    if (val.contains("tên") || val.contains("name") || val.contains("khách")) {
                        nameCol = i;
                        break;
                    }
                }
            }
            if (nameCol < 0 && lastCol > 1) {
                nameCol = (phoneCol == 0) ? 1 : 0;
            }

            if (genderCol < 0) {
                for (int i = 0; i < lastCol; i++) {
                    Cell c = header.getCell(i);
                    if (c == null) continue;
                    String val = CampaignService.text(c).trim().toLowerCase(Locale.ROOT);
                    if (val.contains("giới") || val.contains("gioi") || val.contains("gender") || val.contains("sex")) {
                        genderCol = i;
                        break;
                    }
                }
            }

            String phoneColName = phoneCol >= 0 && header.getCell(phoneCol) != null ? CampaignService.text(header.getCell(phoneCol)) : "ĐT";
            String nameColName = nameCol >= 0 && header.getCell(nameCol) != null ? CampaignService.text(header.getCell(nameCol)) : "TÊN";
            String genderColName = genderCol >= 0 && header.getCell(genderCol) != null ? CampaignService.text(header.getCell(genderCol)) : "Tự động";

            int totalValid = 0;
            int totalInvalid = 0;
            int totalSentSuccess = 0;
            JSONArray preview = new JSONArray();
            List<JSONObject> pendingList = new ArrayList<>();
            List<JSONObject> allValidList = new ArrayList<>();

            for (int i = 1; i <= sheet.getLastRowNum(); i++) {
                Row r = sheet.getRow(i);
                if (r == null) continue;

                String rawPhone = phoneCol >= 0 ? CampaignService.text(r.getCell(phoneCol)) : "";
                String normP = CampaignService.normalizePhone(rawPhone);

                String rawName = nameCol >= 0 ? CampaignService.text(r.getCell(nameCol)) : "";
                String singleName = "";
                if (!rawName.isBlank()) {
                    String[] parts = rawName.trim().split("\\s+");
                    if (parts.length > 0) singleName = parts[parts.length - 1];
                }

                String rawGender = genderCol >= 0 ? CampaignService.text(r.getCell(genderCol)) : "";
                String genderClean = rawGender.trim().toLowerCase(Locale.ROOT);
                if (genderClean.endsWith(".0")) genderClean = genderClean.substring(0, genderClean.length() - 2);
                String genderCode = "";
                String genderLabel = "Tự động";
                if (genderClean.equals("1") || genderClean.equals("nam") || genderClean.equals("anh") || genderClean.equals("m") || genderClean.equals("male")) {
                    genderCode = "1";
                    genderLabel = "1 (Nam / Anh)";
                } else if (genderClean.equals("0") || genderClean.equals("nu") || genderClean.equals("nữ") || genderClean.equals("chi") || genderClean.equals("chị") || genderClean.equals("f") || genderClean.equals("female")) {
                    genderCode = "0";
                    genderLabel = "0 (Nữ / Chị)";
                }

                boolean isSent = false;
                if (sentCol >= 0) {
                    String sentVal = CampaignService.text(r.getCell(sentCol)).trim().toUpperCase(Locale.ROOT);
                    isSent = sentVal.equals("ĐÃ GỬI") || sentVal.equals("DA GUI") || sentVal.equals("TRUE") || sentVal.equals("1") || sentVal.equals("YES") || sentVal.equals("OK");
                }

                JSONObject rowJson = new JSONObject();
                for (int ci = 0; ci < lastCol; ci++) {
                    Cell c = r.getCell(ci);
                    String colKey = (header.getCell(ci) != null) ? CampaignService.text(header.getCell(ci)) : ("Col" + (ci + 1));
                    rowJson.put(colKey, CampaignService.text(c));
                }
                rowJson.put("ĐT", normP != null ? normP : rawPhone);
                rowJson.put("TÊN", rawName);
                rowJson.put("TEN_CUOI", singleName);
                rowJson.put("GIỚI TÍNH", genderCode);
                rowJson.put("GENDER_LABEL", genderLabel);

                if (normP != null) {
                    allValidList.add(rowJson);
                    if (isSent) {
                        totalSentSuccess++;
                    } else {
                        totalValid++;
                        pendingList.add(rowJson);
                    }
                } else {
                    if (!rawPhone.isBlank() || !rawName.isBlank()) {
                        totalInvalid++;
                    }
                }
            }

            List<JSONObject> previewSource = !pendingList.isEmpty() ? pendingList : allValidList;
            for (int i = 0; i < Math.min(previewSource.size(), 8); i++) {
                preview.put(previewSource.get(i));
            }

            result.put("status", "ok");
            result.put("has_excel", true);
            result.put("filename", displayFilename != null ? displayFilename : "dulieu.xlsx");
            result.put("total_valid", totalValid > 0 ? totalValid : allValidList.size());
            result.put("pending_count", totalValid);
            result.put("total_sent_success", totalSentSuccess);
            result.put("total_invalid", totalInvalid);
            result.put("phone_col", phoneColName);
            result.put("name_col", nameColName);
            result.put("gender_col", genderColName);
            result.put("columns", cols);
            result.put("preview", preview);
        }
        return result;
    }

    private static int indexOfBytes(byte[] source, byte[] target, int fromIndex) {
        if (fromIndex >= source.length || target.length == 0) return -1;
        outer:
        for (int i = fromIndex; i <= source.length - target.length; i++) {
            for (int j = 0; j < target.length; j++) {
                if (source[i + j] != target[j]) continue outer;
            }
            return i;
        }
        return -1;
    }

    private static void handleApkDownload(HttpExchange exchange) throws IOException {
        List<Path> candidates = List.of(
            Paths.get("templates", "SmsBridgeSender.apk"),
            Paths.get("android_sender", "SmsBridgeSender-debug.apk"),
            Paths.get("SmsBridgeSender.apk"),
            Paths.get("apk", "SmsBridgeSender.apk")
        );
        for (Path p : candidates) {
            if (Files.isRegularFile(p)) {
                byte[] bytes = Files.readAllBytes(p);
                sendApkResponse(exchange, bytes);
                return;
            }
        }
        try (InputStream in = SmsSenderDesktop.class.getResourceAsStream("/apk/SmsBridgeSender.apk")) {
            if (in != null) {
                byte[] bytes = in.readAllBytes();
                sendApkResponse(exchange, bytes);
                return;
            }
        } catch (Exception ignored) {}

        sendResponse(exchange, 404, "application/json; charset=utf-8", "{\"error\":\"APK not found\"}".getBytes(StandardCharsets.UTF_8));
    }

    private static void sendApkResponse(HttpExchange exchange, byte[] bytes) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", "application/vnd.android.package-archive");
        exchange.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"SmsBridgeSender.apk\"");
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        exchange.sendResponseHeaders(200, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static String getLanIpAddress() {
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.connect(InetAddress.getByName("8.8.8.8"), 10002);
            String ip = socket.getLocalAddress().getHostAddress();
            if (ip != null && !ip.startsWith("127.") && !ip.startsWith("169.254.")) {
                return ip;
            }
        } catch (Exception ignored) {}

        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress addr : Collections.list(ni.getInetAddresses())) {
                    if (addr instanceof Inet4Address && !addr.isLoopbackAddress()) {
                        String h = addr.getHostAddress();
                        if (!h.startsWith("127.") && !h.startsWith("169.254.")) return h;
                    }
                }
            }
        } catch (Exception ignored) {}
        return "127.0.0.1";
    }

    private static void sendJson(HttpExchange exchange, JSONObject json) throws IOException {
        sendJson(exchange, 200, json);
    }

    private static void sendJson(HttpExchange exchange, int status, JSONObject json) throws IOException {
        byte[] bytes = json.toString().getBytes(StandardCharsets.UTF_8);
        sendResponse(exchange, status, "application/json; charset=utf-8", bytes);
    }

    private static void sendResponse(HttpExchange exchange, int status, String contentType, byte[] body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", "*");
        exchange.sendResponseHeaders(status, body.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(body);
        }
    }
}

