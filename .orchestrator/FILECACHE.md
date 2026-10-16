cloud_server.py — cloud relay API and SQLite queue — CloudStore, CloudApi, create_app
test_cloud_server.py — relay self-check — CloudServerSelfCheck
android_sender/app/src/main/java/vn/smsbridge/sender/CloudConfigActivity.kt — Android cloud credentials UI — CloudConfigActivity
android_sender/app/src/main/java/vn/smsbridge/sender/CloudSyncService.kt — Android foreground polling agent — CloudSyncService
android_sender/app/src/main/java/vn/smsbridge/sender/MainActivity.kt — opens cloud configuration — setupListeners
android_sender/app/src/main/AndroidManifest.xml — cloud service permissions and components
android_sender/app/src/main/res/layout/activity_main.xml — cloud configuration button
ios_controller/SmsControllerApp.swift — standalone iOS controller UI and API client — ControllerModel, ContentView
CLOUD_DEPLOY.md — cloud deployment and device provisioning guide
android_sender/app/src/main/java/vn/smsbridge/sender/SmsResultReceiver.kt — uploads carrier result to cloud — onReceive
android_sender/master/build.gradle.kts — Master APK module build config
android_sender/master/src/main/AndroidManifest.xml — Master networking and foreground service declarations
android_sender/master/src/main/java/vn/smsbridge/master/MasterActivity.kt — Master UI and local job enqueue — MasterActivity
android_sender/master/src/main/java/vn/smsbridge/master/MasterServerService.kt — Master LAN HTTP queue server — MasterServerService
android_sender/master/src/main/java/vn/smsbridge/master/MasterStore.kt — Master SQLite job/device state — MasterStore
android_sender/app/src/main/java/vn/smsbridge/sender/CloudConfigActivity.kt — LAN Master validation — isAllowedServer
android_sender/app/src/main/java/vn/smsbridge/sender/CloudSyncService.kt — LAN Master validation — CloudClient.isAllowedServer
ANDROID_MASTER_SETUP.md — local Master/Agent deployment steps
android_sender/app/src/main/java/vn/smsbridge/sender/CloudConfigActivity.kt — Android 6+ service start path — onCreate
android_sender/app/src/main/java/vn/smsbridge/sender/CloudSyncService.kt — cloud configuration lookup — CloudClient.request
android_sender/master/src/main/java/vn/smsbridge/master/MasterServerService.kt — fix job response socket routing — handle
launcher.py — persistent campaign success marker and restart skip — campaign_row_was_sent, mark_campaign_row_sent, worker, android_worker, api_start_campaign
test_launcher.py — Excel campaign marker persistence self-check — test_campaign_success_marker_persists_in_excel
launcher.py — persistent campaign success marker and restart skip — campaign_row_was_sent, mark_campaign_row_sent, worker, android_worker, api_start_campaign
test_launcher.py — Excel campaign marker persistence self-check — test_campaign_success_marker_persists_in_excel
launcher.py — campaign Excel import/export and pause download — ensure_campaign_columns, api_download_campaign_excel, api_upload_excel, stop
templates/index.html — automatic and manual marked campaign Excel download — downloadCampaignExcel, runAction, updateStatusAndLogs
test_launcher.py — imported campaign column creation self-check — test_campaign_import_adds_success_columns
test_launcher.py — campaign marked Excel download self-check — test_campaign_download_exports_marked_excel
android_sender/master/src/main/java/vn/smsbridge/master/MasterStore.kt — Master token storage fix — clusterToken
android_sender/master/src/main/java/vn/smsbridge/master/MasterServerService.kt — Master HTTP header parser fix — readHeader
release/2026-09-05 — built client/master APKs and macOS desktop bundle
release/2026-09-05/README.txt — release install instructions
release/2026-09-05/SHA256SUMS.txt — built artifact integrity hashes
release/2026-09-05/SmsSenderTool-Web-Source.zip — standalone web server release source package
release/2026-09-05/Android_APKs — separate install folder for Master and Client APKs
launcher.py — Zalo browser profile session launcher — find_browser_for_zalo, open_zalo_profile, reset_zalo_profile, api_zalo_open, api_zalo_reset
templates/index.html — Zalo 4-account profile controls — tab-zalo, openZaloSlot, resetZaloSlot
test_launcher.py — Zalo slot validation self-check — test_zalo_profile_rejects_invalid_slot
test_launcher.py — isolated persistent Zalo profile self-check — test_zalo_profiles_use_separate_persistent_directories
release/2026-09-07 — rebuilt desktop/web release with persistent Zalo profile launcher
java_desktop — Java desktop rewrite scaffold with Swing SMS/campaign/Zalo flows
java_desktop/src/main/java/vn/smsbridge/desktop/AdbClient.java — Java ADB SMS bridge client — devices, send
java_desktop/src/main/java/vn/smsbridge/desktop/CampaignService.java — Java Excel campaign runner with persistent success marker — run, export
java_desktop/src/main/java/vn/smsbridge/desktop/ZaloLauncher.java — four persistent Zalo browser profiles — open
java_desktop/src/main/java/vn/smsbridge/desktop/SmsSenderDesktop.java — Java Swing desktop UI — smsPanel, campaignPanel, zaloPanel
java_desktop/build-windows.ps1 — Windows jpackage exe builder
release/2026-09-07/java_desktop — Java app-image and Windows exe build script release
java_desktop/src/main/java/vn/smsbridge/desktop/SmsSenderDesktop.java — separate device selectors per Java UI tab
java_desktop/src/main/java/vn/smsbridge/desktop/CampaignService.java — template customer-name replacement
android_transport.py — derive scan subnets only from active interfaces/ARP; no fixed 192.x subnet
build_apk.ps1 — optional install target from ADB_TARGET
build_direct.ps1 — optional install target from ADB_TARGET
templates/index.html — accepts arbitrary IP or IP:PORT examples
android_sender/app/src/main/java/vn/smsbridge/sender/CloudConfigActivity.kt — generic Master IP hint
release/2026-09-07/Android_APKs/SmsBridgeSender-Client-debug.apk — rebuilt Client without fixed IP assumptions
sms_sender_tool/android_sender/app/src/main/java/vn/smsbridge/sender/CloudConfigActivity.kt — dual LAN/WAN endpoint configuration — lanServer, wanServer
sms_sender_tool/android_sender/app/src/main/java/vn/smsbridge/sender/CloudSyncService.kt — LAN-first/WAN fallback job polling and source-bound result callbacks — nextJob, rememberJobServer, servers
release/2026-09-07/Android_APKs/SmsBridgeSender-Client-LAN-WAN-debug.apk — rebuilt dual LAN/WAN Client APK — CloudSyncService dual endpoint polling
sms_sender_tool/android_sender/app/src/main/java/vn/smsbridge/sender/MainActivity.kt — displays configured WAN Cloud endpoint beside LAN IP — txtWanAddress, updateStatus
sms_sender_tool/android_sender/app/src/main/res/layout/activity_main.xml — LAN/WAN endpoint banner — txt_wan_address
sms_sender_tool/launcher.py — network info includes WAN public IP — get_network_info
sms_sender_tool/templates/index.html — web APK modal displays LAN and WAN public addresses — network-addresses, loadWifiDiscoveryList
sms_sender_tool/android_sender/app/src/main/java/vn/smsbridge/sender/MainActivity.kt — Android Client displays WAN public IP and Cloud URL — txtWanAddress, refreshWanPublicIp
sms_sender_tool/java_desktop/src/main/java/vn/smsbridge/desktop/SmsSenderDesktop.java — Java desktop displays LAN and WAN public IPs — networkPanel, lanIp, wanIp
sms_sender_tool/release/2026-09-07/Android_APKs/SmsBridgeSender-Client-LAN-WAN-debug.apk — rebuilt Client with LAN/WAN address display — MainActivity network banner
android_sender/app/src/main/java/vn/smsbridge/sender/SmsCommandReceiver.kt — reports active in-service SIM subscriptions — ACTION_SIM_STATUS, writeSimStatus
android_transport.py — queries active SIM channels — active_subscription_ids
launcher.py — dual-SIM virtual campaign workers — android_worker, run_android_worker, start
test_android_transport.py — active SIM filtering check — test_active_subscription_ids_uses_only_in_service_sims
release/2026-09-07/Android_APKs/SmsBridgeSender-Client-LAN-WAN-debug.apk — rebuilt Client with SIM status reporting — SmsCommandReceiver SIM_STATUS
java_desktop/src/main/java/vn/smsbridge/desktop/SmsSenderDesktop.java — dark card-based desktop UI matching web visual language — header, page, card, styleButton, logPanel
app_desktop.py — native WebView wrapper renders exact web UI across Windows/macOS — main
launcher.py — APK LAN URLs use actual runtime desktop port — get_network_info
requirements.txt — native desktop WebView runtime — pywebview 6.2.1
platform-tools/adb — bundled macOS ADB for desktop/web auto-detection — resolve_adb_path local candidate
launcher.py — restores ADB availability status when local/bundled ADB exists — detect_adb_status
templates/index.html — fixes generic active tab rendering so Zalo cards display — tab-content.active
templates/index.html — independent ADB badge polling and explicit bundled ADB ready state — renderAdbBadge, refreshAdbBadge
sms_new — clean source snapshot plus release artifacts copied from sms_sender_tool — source, platform-tools, release
android_transport.py — restores legacy hotspot discovery and scans all active interface subnets — _get_lan_ip_candidates
build_exe.py — Windows-only PyInstaller packager validates EXE and bundled ADB runtime files — build, verify_windows_bundle
sms_new/build_exe.py — synced Windows packaging validation — build, verify_windows_bundle
build_exe.py — Windows-only PyInstaller packager validates EXE and bundled ADB runtime files — build, verify_windows_bundle
sms_new/build_exe.py — synced Windows packaging validation — build, verify_windows_bundle
build_exe.py — returns nonzero on failed/non-Windows Windows-EXE build — __main__
sms_new/build_exe.py — synced nonzero package exit status — __main__
BUILD_WINDOWS.bat — one-click Windows bootstrap, PyInstaller build, ADB bundle validation, and app launch — full script
sms_new/BUILD_WINDOWS.bat — synced one-click Windows packaging launcher — full script
launcher.py — campaign queue, status transition guards, delivery accounting — Campaign, CampaignManager, update_android_status, /start, /api/campaigns
test_launcher.py — regression coverage for delivery semantics and multi-campaign API — DeliveredOnlySuccessAndMultiCampaignTests
test_android_transport.py — transport regression coverage — AndroidTransportSelfCheck
android_sender/app/src/main/AndroidManifest.xml — wake lock, battery optimization, and boot restart permissions/receiver registration — CloudSyncService, BootReceiver
android_sender/app/src/main/java/vn/smsbridge/sender/CloudSyncService.kt — foreground cloud polling, screen-off locks, shared result executor, persisted result outbox — CloudSyncService, reportResult, Outbox, flush
android_sender/app/src/main/java/vn/smsbridge/sender/BootReceiver.kt — restarts configured cloud service after boot or package replacement — BootReceiver.onReceive
/Users/107536-nhatnhm/.codex/skills/antigravity-supervised-coding/SKILL.md — Codex skill — active Antigravity supervision loop, stall takeover rules
/Users/107536-nhatnhm/.codex/skills/antigravity-supervised-coding/SKILL.md — Codex skill — mandatory 9Router probe, measurable progress, two-interval takeover
/Users/107536-nhatnhm/.codex/skills/antigravity-supervised-coding/SKILL.md — Codex skill — 9Router worker inventory, capability-based assignment, managed supervision
