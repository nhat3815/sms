import SwiftUI

@main
struct SmsControllerApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct Device: Codable, Identifiable {
    let id: String
    let name: String
    let last_seen: String?
}

struct DevicesResponse: Codable { let devices: [Device] }

@MainActor
final class ControllerModel: ObservableObject {
    @Published var serverURL = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    @Published var operatorToken = UserDefaults.standard.string(forKey: "operatorToken") ?? ""
    @Published var devices: [Device] = []
    @Published var selectedDevice = ""
    @Published var phone = ""
    @Published var message = ""
    @Published var status = ""

    func loadDevices() async { await run(path: "/v1/devices", method: "GET", body: nil) { data in
        self.devices = try JSONDecoder().decode(DevicesResponse.self, from: data).devices
        if self.selectedDevice.isEmpty { self.selectedDevice = self.devices.first?.id ?? "" }
    }}

    func send() async {
        let body: [String: Any] = ["device_id": selectedDevice, "phone": phone, "message": message]
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return }
        await run(path: "/v1/jobs", method: "POST", body: data) { _ in
            self.status = "Đã xếp hàng gửi"
            self.phone = ""
            self.message = ""
        }
    }

    private func run(path: String, method: String, body: Data?, success: @escaping (Data) throws -> Void) async {
        guard let url = URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines) + path), url.scheme == "https" else {
            status = "Server phải dùng HTTPS"
            return
        }
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        UserDefaults.standard.set(operatorToken, forKey: "operatorToken")
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue(operatorToken, forHTTPHeaderField: "X-Operator-Token")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
                status = "API từ chối yêu cầu"
                return
            }
            try success(data)
        } catch { status = error.localizedDescription }
    }
}

struct ContentView: View {
    @StateObject private var model = ControllerModel()

    var body: some View {
        NavigationStack {
            Form {
                Section("Cloud") {
                    TextField("https://sms.example.com", text: $model.serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                    SecureField("Operator token", text: $model.operatorToken)
                    Button("Kết nối") { Task { await model.loadDevices() } }
                }
                Section("Gửi SMS") {
                    Picker("Máy Android", selection: $model.selectedDevice) {
                        ForEach(model.devices) { Text($0.name).tag($0.id) }
                    }
                    TextField("Số điện thoại", text: $model.phone).keyboardType(.phonePad)
                    TextEditor(text: $model.message).frame(minHeight: 120)
                    Button("Gửi") { Task { await model.send() } }
                        .disabled(model.selectedDevice.isEmpty || model.phone.isEmpty || model.message.isEmpty)
                }
                if !model.status.isEmpty { Text(model.status) }
            }
            .navigationTitle("SMS Controller")
        }
    }
}
