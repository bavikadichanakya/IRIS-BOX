Create the hardware firmware module and setup documentation for the physical IRIS Smart Speaker pod.

Requirements:
1. Create a new directory irmware/iris_pod/ containing:
   - iris_satellite.ino: Complete Arduino/PlatformIO C++ sketch for ESP32-S3 DevKit.
   - I2S configuration for INMP441 MEMS microphone (16kHz 16-bit RX).
   - I2S configuration for MAX98357A Class-D amplifier (16kHz 16-bit TX).
   - Asynchronous WebSocket client streaming mic frames to ws://<server_ip>:8000/ws/audio and playing incoming audio chunks.
2. Create docs/HARDWARE_SETUP.md:
   - Full wiring pinout table (ESP32-S3 GPIO pins for INMP441 and MAX98357A).
   - Power supply recommendations (5V 2A USB-C).
   - Flashing instructions via Arduino IDE / esptool.
3. Ensure the project builds cleanly without modifying existing server tests.
