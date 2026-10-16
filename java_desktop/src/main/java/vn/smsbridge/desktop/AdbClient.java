package vn.smsbridge.desktop;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

public final class AdbClient {
    private static final String PACKAGE = "vn.smsbridge.sender";
    private final Path adb;

    public AdbClient() {
        adb = resolveAdb();
    }

    public boolean isAvailable() {
        return adb != null;
    }

    public static final class DeviceInfo {
        private final String serial;
        private final String model;
        private final boolean ready;

        public DeviceInfo(String serial, String model, boolean ready) {
            this.serial = serial != null ? serial : "";
            this.model = model != null ? model : "";
            this.ready = ready;
        }

        public String serial() { return serial; }
        public String model() { return model; }
        public boolean ready() { return ready; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof DeviceInfo)) return false;
            DeviceInfo that = (DeviceInfo) o;
            return ready == that.ready &&
                java.util.Objects.equals(serial, that.serial) &&
                java.util.Objects.equals(model, that.model);
        }

        @Override
        public int hashCode() {
            return java.util.Objects.hash(serial, model, ready);
        }

        @Override
        public String toString() {
            return "DeviceInfo[serial=" + serial + ", model=" + model + ", ready=" + ready + "]";
        }
    }

    public List<DeviceInfo> listDevices() {
        List<DeviceInfo> list = new ArrayList<>();
        try {
            CommandResult result = run(List.of("devices", "-l"), 10);
            if (result.exitCode() == 0) {
                for (String line : result.output().split("\\R")) {
                    String trimmed = line.trim();
                    if (trimmed.isEmpty() || trimmed.startsWith("*") || trimmed.startsWith("List")) continue;
                    String[] parts = trimmed.split("\\s+");
                    if (parts.length >= 2 && "device".equals(parts[1])) {
                        String serial = parts[0];
                        String model = "Android Device";
                        for (String part : parts) {
                            if (part.startsWith("model:")) model = part.substring(6).replace("_", " ");
                        }
                        list.add(new DeviceInfo(serial, model, true));
                    }
                }
            }
        } catch (Exception ignored) {}
        return list;
    }

    public List<String> devices() throws IOException, InterruptedException {
        CommandResult result = run(List.of("devices", "-l"), 10);
        if (result.exitCode() != 0) throw new IOException(result.output());
        List<String> devices = new ArrayList<>();
        for (String line : result.output().split("\\R")) {
            String[] fields = line.trim().split("\\s+");
            if (fields.length >= 2 && "device".equals(fields[1])) devices.add(fields[0]);
        }
        return devices;
    }

    public List<Integer> getActiveSubscriptions(String serial) {
        List<Integer> list = new ArrayList<>();
        if (serial == null || serial.isBlank()) return List.of(-1);
        try {
            String token = readBridgeToken(serial);
            run(List.of(
                "-s", serial, "shell", "am", "broadcast",
                "-n", PACKAGE + "/.SmsCommandReceiver",
                "-a", PACKAGE + ".SIM_STATUS",
                "--es", "token", token
            ), 5);
            CommandResult cat = run(List.of("-s", serial, "shell", "run-as", PACKAGE, "cat", "files/sim_status.json"), 4);
            if (cat.exitCode() == 0 && cat.output().contains("subscriptions")) {
                org.json.JSONObject obj = new org.json.JSONObject(cat.output().trim());
                org.json.JSONArray subs = obj.optJSONArray("subscriptions");
                if (subs != null) {
                    for (int i = 0; i < subs.length(); i++) {
                        org.json.JSONObject s = subs.getJSONObject(i);
                        if (s.optBoolean("in_service", true)) {
                            int subId = s.optInt("subscription_id", -1);
                            if (subId >= 0) list.add(subId);
                        }
                    }
                }
            }
        } catch (Exception ignored) {}
        return list.isEmpty() ? List.of(-1) : list;
    }

    public CommandResult send(String serial, String phone, String message) throws IOException, InterruptedException {
        return send(serial, phone, message, -1, UUID.randomUUID().toString());
    }

    public CommandResult send(String serial, String phone, String message, int subscriptionId, String jobId) throws IOException, InterruptedException {
        if (serial == null || serial.isBlank() || "AUTO".equalsIgnoreCase(serial)) {
            List<String> devs = devices();
            if (devs.isEmpty()) throw new IOException("Không có thiết bị Android nào kết nối");
            serial = devs.get(0);
        }
        if (!phone.matches("\\+?[0-9]{8,15}")) throw new IllegalArgumentException("Số điện thoại không hợp lệ");
        if (message == null || message.isBlank()) throw new IllegalArgumentException("Nội dung trống");
        String token = readBridgeToken(serial);
        String encoded = Base64.getEncoder().encodeToString(message.getBytes(StandardCharsets.UTF_8));
        List<String> cmd = new ArrayList<>(List.of(
            "-s", serial, "shell", "am", "broadcast",
            "-a", PACKAGE + ".SEND_SMS",
            "-n", PACKAGE + "/.SmsCommandReceiver",
            "--es", "job_id", jobId,
            "--es", "phone", phone,
            "--es", "message_b64", encoded,
            "--es", "token", token
        ));
        if (subscriptionId >= 0) {
            cmd.add("--ei");
            cmd.add("subscription_id");
            cmd.add(String.valueOf(subscriptionId));
        }
        return run(cmd, 20);
    }

    public String checkJobStatus(String serial, String jobId, int timeoutSeconds) {
        long start = System.currentTimeMillis();
        while (System.currentTimeMillis() - start < timeoutSeconds * 1000L) {
            try {
                Thread.sleep(1000L);
                CommandResult res = run(List.of("-s", serial, "shell", "run-as", PACKAGE, "cat", "files/events.jsonl"), 4);
                if (res.exitCode() == 0 && res.output().contains(jobId)) {
                    for (String line : res.output().split("\\R")) {
                        if (line.contains(jobId)) {
                            try {
                                org.json.JSONObject json = new org.json.JSONObject(line.trim());
                                String stage = json.optString("stage", "");
                                boolean isSuccess = json.optBoolean("is_success", true);
                                if ("FAILED".equals(stage) || !isSuccess) {
                                    String err = json.optString("error", "Lỗi nhà mạng");
                                    return "FAILED:" + err;
                                }
                                if ("SENT".equals(stage) || "DELIVERED".equals(stage)) {
                                    return "SUCCESS";
                                }
                            } catch (Exception ignored) {}
                        }
                    }
                }
            } catch (Exception ignored) {}
        }
        return "TIMEOUT";
    }

    private String readBridgeToken(String serial) {
        try {
            CommandResult result = run(List.of("-s", serial, "shell", "run-as", PACKAGE, "cat", "files/bridge_token"), 5);
            String token = result.output().trim();
            if (result.exitCode() == 0 && !token.isBlank() && !token.contains("error") && !token.contains("not debuggable")) {
                return token;
            }
        } catch (Exception ignored) {}
        return "123";
    }

    public CommandResult run(List<String> args, int timeoutSeconds) throws IOException, InterruptedException {
        if (adb == null) throw new IOException("Không tìm thấy ADB");
        List<String> command = new ArrayList<>();
        command.add(adb.toString());
        command.addAll(args);
        Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
        boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
        if (!finished) {
            process.destroyForcibly();
            throw new IOException("ADB timeout");
        }
        return new CommandResult(process.exitValue(), new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8));
    }

    private static Path resolveAdb() {
        List<String> candidates = new ArrayList<>();
        String env = System.getenv("ADB_PATH");
        if (env != null) candidates.add(env);
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        boolean isWin = os.contains("win");
        String binary = isWin ? "adb.exe" : "adb";

        candidates.add(Paths.get("platform-tools", binary).toAbsolutePath().toString());
        candidates.add(Paths.get(System.getProperty("user.home"), ".sms-sender-tool", "platform-tools", binary).toString());
        candidates.add("/opt/homebrew/bin/adb");
        candidates.add("/usr/local/bin/adb");
        candidates.add("/opt/homebrew/share/android-commandlinetools/platform-tools/adb");
        String path = System.getenv("PATH");
        if (path != null) {
            for (String directory : path.split(java.io.File.pathSeparator)) {
                candidates.add(Paths.get(directory, binary).toString());
            }
        }

        for (String c : candidates) {
            Path p = Paths.get(c);
            if (Files.isRegularFile(p)) {
                p.toFile().setExecutable(true, false);
                return p;
            }
        }

        // Tự động giải nén file ADB đi kèm trong JAR ra thư mục người dùng
        return extractBundledAdb(isWin, binary);
    }

    private static Path extractBundledAdb(boolean isWin, String binary) {
        try {
            Path destDir = Paths.get(System.getProperty("user.home"), ".sms-sender-tool", "platform-tools");
            Files.createDirectories(destDir);
            String[] files = isWin
                ? new String[]{"adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"}
                : new String[]{"adb"};

            for (String f : files) {
                Path dest = destDir.resolve(f);
                if (!Files.exists(dest) || Files.size(dest) == 0) {
                    try (var in = AdbClient.class.getResourceAsStream("/platform-tools/" + f)) {
                        if (in != null) {
                            Files.copy(in, dest, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                            dest.toFile().setExecutable(true, false);
                        }
                    }
                }
            }
            Path target = destDir.resolve(binary);
            if (Files.isRegularFile(target)) {
                target.toFile().setExecutable(true, false);
                return target;
            }
        } catch (Exception e) {
            System.err.println("Lỗi giải nén bundled ADB: " + e.getMessage());
        }
        return null;
    }

    public static final class CommandResult {
        private final int exitCode;
        private final String output;

        public CommandResult(int exitCode, String output) {
            this.exitCode = exitCode;
            this.output = output != null ? output : "";
        }

        public int exitCode() { return exitCode; }
        public String output() { return output; }

        public boolean successful() {
            String lower = output.toLowerCase(Locale.ROOT);
            return exitCode == 0 && (lower.contains("broadcast completed") || lower.contains("result=-1"));
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof CommandResult)) return false;
            CommandResult that = (CommandResult) o;
            return exitCode == that.exitCode && java.util.Objects.equals(output, that.output);
        }

        @Override
        public int hashCode() {
            return java.util.Objects.hash(exitCode, output);
        }

        @Override
        public String toString() {
            return "CommandResult[exit=" + exitCode + ", output=" + output + "]";
        }
    }
}
