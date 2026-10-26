import AVFoundation
import CoreImage
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}
func emit(_ object: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: object) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}
func cameras() -> [AVCaptureDevice] {
    var types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera]
    if #available(macOS 14.0, *) { types += [.external, .continuityCamera] }
    else { types += [.externalUnknown] }
    return AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
}
let args = CommandLine.arguments
if args.count < 2 || args[1] == "--help" {
    print("RodentWatchCapture --list | --camera DEVICE_ID")
    exit(0)
}
// Listing does not start a camera or request permission.
if args[1] == "--list" {
    for device in cameras() {
        emit(["id": device.uniqueID, "name": device.localizedName,
              "type": device.deviceType.rawValue])
    }
    exit(0)
}
guard args.count == 3 && args[1] == "--camera" else { fail("Expected --camera DEVICE_ID") }
switch AVCaptureDevice.authorizationStatus(for: .video) {
case .notDetermined:
    var allowed = false
    let done = DispatchSemaphore(value: 0)
    AVCaptureDevice.requestAccess(for: .video) { granted in allowed = granted; done.signal() }
    done.wait()
    if !allowed { fail("Camera permission denied. Enable Camera access in System Settings > Privacy & Security for Rodent Watch Camera or your terminal.") }
case .authorized: break
 default: fail("Camera permission denied or restricted. Check System Settings > Privacy & Security > Camera.")
}
guard let device = cameras().first(where: { $0.uniqueID == args[2] }) else {
    fail("Selected camera is unavailable. Check iPhone Continuity Camera, Wi-Fi, Bluetooth and proximity.")
}
let session = AVCaptureSession()
let input: AVCaptureDeviceInput
do { input = try AVCaptureDeviceInput(device: device) }
catch { fail("Cannot open camera: \(error.localizedDescription)") }
session.beginConfiguration()
if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
guard session.canAddInput(input) else { fail("Cannot attach camera input") }
session.addInput(input)
let output = AVCaptureVideoDataOutput()
output.alwaysDiscardsLateVideoFrames = true
output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
guard session.canAddOutput(output) else { fail("Cannot attach camera output") }
session.addOutput(output)

class Receiver: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let context = CIContext()
    var last = 0.0
    func captureOutput(_ output: AVCaptureOutput, didOutput sample: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = ProcessInfo.processInfo.systemUptime
        guard now - last >= 0.1, let buffer = CMSampleBufferGetImageBuffer(sample) else { return }
        last = now
        autoreleasepool {
            let image = CIImage(cvPixelBuffer: buffer)
            if let jpeg = context.jpegRepresentation(of: image, colorSpace: CGColorSpaceCreateDeviceRGB(), options: [:]) {
                emit(["uptime": now, "jpeg": jpeg.base64EncodedString()])
            }
        }
    }
}
let receiver = Receiver()
output.setSampleBufferDelegate(receiver, queue: DispatchQueue(label: "local.rodentwatch.frames"))
session.commitConfiguration()
let observer = NotificationCenter.default.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: session, queue: nil) { note in
    fail("Camera runtime error: \(note.userInfo?[AVCaptureSessionErrorKey] ?? "unknown")")
}
session.startRunning()
RunLoop.main.run()
