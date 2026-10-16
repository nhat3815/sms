package vn.smsbridge.desktop;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

public final class ZaloLauncher {
    private final Path baseDir;

    public ZaloLauncher(Path baseDir) {
        this.baseDir = baseDir;
    }

    public void open(int slot) throws IOException {
        if (slot < 1 || slot > 4) throw new IllegalArgumentException("Slot 1-4");
        String browser = browser();
        Path profile = baseDir.resolve(String.format("zalo_%02d", slot));
        Files.createDirectories(profile);
        int width = 720;
        int height = 620;
        int left = 40 + ((slot - 1) % 2) * width;
        int top = 40 + ((slot - 1) / 2) * height;
        new ProcessBuilder(List.of(
            browser,
            "--new-window",
            "--app=https://chat.zalo.me/",
            "--user-data-dir=" + profile,
            "--window-size=" + width + "," + height,
            "--window-position=" + left + "," + top,
            "--no-first-run",
            "--no-default-browser-check"
        )).start();
    }

    private String browser() throws IOException {
        List<String> candidates = new ArrayList<>();
        String configured = System.getenv("SMS_BROWSER_PATH");
        if (configured != null && !configured.isBlank()) candidates.add(configured);
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        if (os.contains("win")) {
            String programFiles = System.getenv().getOrDefault("ProgramFiles", "C:\\Program Files");
            String programFilesX86 = System.getenv().getOrDefault("ProgramFiles(x86)", "C:\\Program Files (x86)");
            String localAppData = System.getenv().getOrDefault("LOCALAPPDATA", "");
            candidates.add(programFiles + "\\Google\\Chrome\\Application\\chrome.exe");
            candidates.add(programFilesX86 + "\\Google\\Chrome\\Application\\chrome.exe");
            candidates.add(localAppData + "\\Google\\Chrome\\Application\\chrome.exe");
            candidates.add(programFiles + "\\Microsoft\\Edge\\Application\\msedge.exe");
            candidates.add(programFilesX86 + "\\Microsoft\\Edge\\Application\\msedge.exe");
        } else if (os.contains("mac")) {
            candidates.add("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
            candidates.add("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge");
        } else {
            candidates.add("google-chrome");
            candidates.add("chromium");
            candidates.add("microsoft-edge");
        }
        return candidates.stream().filter(path -> Files.isRegularFile(Path.of(path))).findFirst()
            .orElseThrow(() -> new IOException("Không tìm thấy Chrome hoặc Edge"));
    }

    public void reset(int slot) throws IOException {
        Path profile = baseDir.resolve(String.format("zalo_%02d", slot));
        if (Files.exists(profile)) {
            try (var stream = Files.walk(profile)) {
                stream.sorted(Comparator.reverseOrder()).forEach(p -> {
                    try { Files.delete(p); } catch (Exception ignored) {}
                });
            }
        }
    }
}
