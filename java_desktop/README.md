# Java Desktop

## macOS test build

```sh
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
gradle packageMacApp
```

## Windows installer

Run `build-windows.ps1` on Windows with JDK 17+ and Gradle 8+. It produces a self-contained `SmsSenderTool-2.0.0.exe`; end users do not install Java.
