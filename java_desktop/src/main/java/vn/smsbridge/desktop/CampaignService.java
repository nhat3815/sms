package vn.smsbridge.desktop;

import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

public final class CampaignService {
    public static final String SUCCESS = "ĐÃ GỬI THÀNH CÔNG";
    public static final String SUCCESS_AT = "THỜI GIAN GỬI THÀNH CÔNG";

    public static final class TargetChannel {
        private final String deviceId;
        private final int subscriptionId;
        private final String label;

        public TargetChannel(String deviceId, int subscriptionId, String label) {
            this.deviceId = deviceId != null ? deviceId : "";
            this.subscriptionId = subscriptionId;
            this.label = label != null ? label : "";
        }

        public String deviceId() { return deviceId; }
        public int subscriptionId() { return subscriptionId; }
        public String label() { return label; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof TargetChannel)) return false;
            TargetChannel that = (TargetChannel) o;
            return subscriptionId == that.subscriptionId &&
                java.util.Objects.equals(deviceId, that.deviceId) &&
                java.util.Objects.equals(label, that.label);
        }

        @Override
        public int hashCode() {
            return java.util.Objects.hash(deviceId, subscriptionId, label);
        }

        @Override
        public String toString() {
            return "TargetChannel[" + label + ", dev=" + deviceId + ", sub=" + subscriptionId + "]";
        }
    }

    @FunctionalInterface
    public interface SmsSender {
        boolean send(TargetChannel channel, String phone, String message, String customerName) throws Exception;
    }

    private final SmsSender sender;
    private final AtomicBoolean running = new AtomicBoolean();
    private final AtomicInteger sentCount = new AtomicInteger();
    private final AtomicInteger totalCount = new AtomicInteger();
    private final AtomicInteger successCount = new AtomicInteger();

    public CampaignService(AdbClient adb) {
        this((channel, phone, msg, name) -> adb.send(channel.deviceId(), phone, msg, channel.subscriptionId(), java.util.UUID.randomUUID().toString()).successful());
    }

    public CampaignService(SmsSender sender) {
        this.sender = sender;
    }

    public boolean isRunning() {
        return running.get();
    }

    public int getSentCount() { return sentCount.get(); }
    public int getTotalCount() { return totalCount.get(); }
    public int getSuccessCount() { return successCount.get(); }

    public void stop() {
        running.set(false);
    }

    public void run(Path file, String serial, List<String> templates, int delaySeconds, Consumer<String> log) {
        run(file, List.of(new TargetChannel(serial, -1, serial)), templates, delaySeconds, log);
    }

    public void run(Path file, List<TargetChannel> channels, List<String> templates, int delaySeconds, Consumer<String> log) {
        if (!running.compareAndSet(false, true)) throw new IllegalStateException("Chiến dịch đang chạy");
        sentCount.set(0);
        successCount.set(0);
        List<TargetChannel> activeChannels = (channels == null || channels.isEmpty())
            ? List.of(new TargetChannel("AUTO", -1, "Android"))
            : channels;

        try (InputStream input = Files.newInputStream(file); Workbook workbook = WorkbookFactory.create(input)) {
            Sheet sheet = workbook.getSheetAt(0);
            Row header = sheet.getRow(0);
            if (header == null) throw new IOException("Excel thiếu dòng tiêu đề");

            int phoneColumn = findColumn(header,
                "ĐT", "ĐIỆN THOẠI", "DIEN THOAI", "SDT", "SĐT", "SO DIEN THOAI", "SỐ ĐIỆN THOẠI",
                "PHONE", "TEL", "MOBILE", "PHONE NUMBER", "SO_DIEN_THOAI", "DIEN_THOAI");
            int nameColumn = findColumn(header,
                "TÊN", "TEN", "NAME", "HỌ TÊN", "HO TEN", "HỌ VÀ TÊN", "HO VA TEN",
                "HOTEN", "KHACH HANG", "KHÁCH HÀNG", "CUSTOMER", "FULLNAME");
            int genderColumn = findColumn(header,
                "GIỚI TÍNH", "GIOI TINH", "GENDER", "SEX", "PHÁI", "PHAI", "XƯNG HÔ", "XUNG HO");

            if (phoneColumn < 0) {
                for (Cell c : header) {
                    String v = text(c).trim().toLowerCase(Locale.ROOT);
                    if (v.contains("phone") || v.contains("sdt") || v.contains("điện thoại") || v.contains("dien thoai") || v.contains("đt")) {
                        phoneColumn = c.getColumnIndex();
                        break;
                    }
                }
            }
            if (phoneColumn < 0 && header.getLastCellNum() > 0) {
                phoneColumn = 0;
            }

            int successColumn = ensureColumn(header, SUCCESS);
            int successAtColumn = ensureColumn(header, SUCCESS_AT);
            save(workbook, file);

            final int finalPhoneCol = phoneColumn;
            final int finalNameCol = nameColumn;
            final int finalGenderCol = genderColumn;
            final int finalSuccessCol = successColumn;
            final int finalSuccessAtCol = successAtColumn;

            List<Integer> targetRowIndices = new ArrayList<>();
            Set<String> seenExcelPhones = new HashSet<>();
            for (int i = 1; i <= sheet.getLastRowNum(); i++) {
                Row r = sheet.getRow(i);
                if (r != null && !isSent(r.getCell(finalSuccessCol))) {
                    String p = normalizePhone(text(r.getCell(finalPhoneCol)));
                    if (p != null) {
                        if (seenExcelPhones.add(p)) {
                            targetRowIndices.add(i);
                        } else {
                            log.accept("⏩ Bỏ qua dòng " + (i + 1) + ": Số điện thoại " + p + " bị trùng lặp trong file Excel");
                        }
                    }
                }
            }
            totalCount.set(targetRowIndices.size());

            if (targetRowIndices.isEmpty()) {
                log.accept("⚠️ Tất cả khách hàng trong danh sách đã gửi thành công trước đó.");
                return;
            }

            int channelCount = activeChannels.size();
            Set<String> dispatchedPhones = ConcurrentHashMap.newKeySet();
            java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(channelCount);
            java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(channelCount);

            for (int c = 0; c < channelCount; c++) {
                final int channelIdx = c;
                final TargetChannel ch = activeChannels.get(c);
                final List<Integer> myRows = new ArrayList<>();
                for (int j = 0; j < targetRowIndices.size(); j++) {
                    if (j % channelCount == channelIdx) {
                        myRows.add(targetRowIndices.get(j));
                    }
                }

                pool.execute(() -> {
                    try {
                        int templateIndex = 0;
                        for (int rowIndex : myRows) {
                            if (!running.get()) break;

                            String rawPhone, phone, rawName, singleName, displayName, message;
                            synchronized (workbook) {
                                Row row = sheet.getRow(rowIndex);
                                if (row == null || isSent(row.getCell(finalSuccessCol))) continue;
                                rawPhone = text(row.getCell(finalPhoneCol));
                                phone = normalizePhone(rawPhone);
                                if (phone == null) continue;

                                if (!dispatchedPhones.add(phone)) {
                                    log.accept("⏩ Bỏ qua " + phone + ": Đã gửi hoặc đang xử lý bởi kênh khác");
                                    continue;
                                }

                                rawName = finalNameCol >= 0 ? text(row.getCell(finalNameCol)) : "";
                                singleName = "";
                                if (!rawName.isBlank()) {
                                    String[] parts = rawName.trim().split("\\s+");
                                    if (parts.length > 0) singleName = parts[parts.length - 1];
                                }

                                String rawGender = finalGenderCol >= 0 ? text(row.getCell(finalGenderCol)) : "";
                                String g = rawGender.trim().toLowerCase(Locale.ROOT);
                                if (g.endsWith(".0")) g = g.substring(0, g.length() - 2);

                                String xungho = "Anh/Chị";
                                if (g.equals("1") || g.equals("nam") || g.equals("anh") || g.equals("m") || g.equals("male")) {
                                    xungho = "Anh";
                                } else if (g.equals("0") || g.equals("nu") || g.equals("nữ") || g.equals("chi") || g.equals("chị") || g.equals("f") || g.equals("female")) {
                                    xungho = "Chị";
                                }

                                displayName = !singleName.isBlank() ? (xungho.equals("Anh/Chị") ? singleName : (xungho + " " + singleName)) : xungho;
                                if (singleName.isBlank()) singleName = displayName;

                                String template = templates.get(templateIndex++ % templates.size());
                                message = template
                                    .replace("{xungho}", xungho)
                                    .replace("{ten}", singleName)
                                    .replace("{tencuoi}", singleName)
                                    .replace("{name}", displayName)
                                    .replace("{fullname}", !rawName.isBlank() ? rawName : displayName)
                                    .replace("{hoten}", !rawName.isBlank() ? rawName : displayName)
                                    .replace("{HOTEN}", !rawName.isBlank() ? rawName : displayName)
                                    .replace("{TEN}", singleName);

                                for (Cell hCell : header) {
                                    String colName = text(hCell).trim();
                                    if (!colName.isBlank()) {
                                        Cell valCell = row.getCell(hCell.getColumnIndex());
                                        String val = text(valCell);
                                        message = message.replace("{" + colName + "}", val);
                                        message = message.replace("{" + colName.toLowerCase(Locale.ROOT) + "}", val);
                                        message = message.replace("{" + colName.toUpperCase(Locale.ROOT) + "}", val);
                                    }
                                }
                            }

                            sentCount.incrementAndGet();
                            boolean ok = false;
                            try {
                                ok = sender.send(ch, phone, message, rawName);
                            } catch (Exception ex) {
                                log.accept("Lỗi gửi tin tới " + phone + ": " + ex.getMessage());
                            }

                            if (ok) {
                                successCount.incrementAndGet();
                                synchronized (workbook) {
                                    Row row = sheet.getRow(rowIndex);
                                    if (row != null) {
                                        row.createCell(finalSuccessCol, CellType.STRING).setCellValue("ĐÃ GỬI");
                                        row.createCell(finalSuccessAtCol, CellType.STRING).setCellValue(LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
                                        save(workbook, file);
                                    }
                                }
                                log.accept("✅ ĐÃ GỬI [" + ch.label() + "]: " + phone + " (" + displayName + ")");
                            } else {
                                log.accept("❌ GỬI THẤT BẠI [" + ch.label() + "]: " + phone + " (" + displayName + ")");
                            }

                            if (running.get() && delaySeconds > 0) {
                                long endTime = System.currentTimeMillis() + (delaySeconds * 1000L);
                                while (running.get() && System.currentTimeMillis() < endTime) {
                                    long waitStep = Math.min(200L, endTime - System.currentTimeMillis());
                                    if (waitStep > 0) Thread.sleep(waitStep);
                                }
                            }
                        }
                    } catch (Exception e) {
                        log.accept("Lỗi luồng " + ch.label() + ": " + e.getMessage());
                    } finally {
                        latch.countDown();
                    }
                });
            }
            latch.await();
            pool.shutdown();
        } catch (Exception error) {
            log.accept("ERROR: " + error.getMessage());
        } finally {
            running.set(false);
        }
    }

    public void export(Path source, Path destination) throws IOException {
        Files.copy(source, destination, StandardCopyOption.REPLACE_EXISTING);
    }

    private static boolean isSent(Cell cell) {
        if (cell == null) return false;
        String val = text(cell).trim().toUpperCase(Locale.ROOT);
        return val.equals("ĐÃ GỬI") || val.equals("DA GUI") || val.equals("TRUE") || val.equals("1") || val.equals("YES") || val.equals("OK");
    }

    private static int findColumn(Row header, String... names) {
        for (Cell cell : header) {
            String value = text(cell).trim().toUpperCase(Locale.ROOT);
            for (String name : names) {
                if (value.equals(name.toUpperCase(Locale.ROOT))) return cell.getColumnIndex();
            }
        }
        return -1;
    }

    private static int ensureColumn(Row header, String name) {
        int existing = findColumn(header, name);
        if (existing >= 0) return existing;
        int index = Math.max(0, header.getLastCellNum());
        header.createCell(index, CellType.STRING).setCellValue(name);
        return index;
    }

    public static String text(Cell cell) {
        if (cell == null) return "";
        if (cell.getCellType() == CellType.NUMERIC) {
            double d = cell.getNumericCellValue();
            if (d == Math.floor(d)) {
                return String.format(Locale.ROOT, "%.0f", d);
            }
            return String.valueOf(d);
        }
        if (cell.getCellType() == CellType.BOOLEAN) {
            return String.valueOf(cell.getBooleanCellValue());
        }
        return cell.toString().trim();
    }

    public static String normalizePhone(String raw) {
        if (raw == null) return null;
        String digits = raw.replaceAll("[^0-9]", "");
        if (digits.startsWith("84") && digits.length() == 11) {
            digits = "0" + digits.substring(2);
        }
        if (digits.length() == 9) {
            digits = "0" + digits;
        }
        if (digits.length() == 10 && digits.startsWith("0")) {
            return digits;
        }
        if (digits.matches("^[0-9]{8,15}$")) {
            return digits;
        }
        return null;
    }

    private static void save(Workbook workbook, Path file) throws IOException {
        Path temp = file.resolveSibling(file.getFileName() + ".tmp.xlsx");
        try (OutputStream output = Files.newOutputStream(temp)) {
            workbook.write(output);
        }
        Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING);

        try {
            Path rootDulieu = Paths.get("dulieu.xlsx");
            if (!Files.isSameFile(file, rootDulieu)) {
                Files.copy(file, rootDulieu, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (Exception ignored) {}
    }
}
