import os
from src.models.schemas import PhoneCameraVisionAction
from src.vision.phone_camera import PhoneCameraTool

def main():
    print("[*] Testing PhoneCameraTool live against Ollama qwen3.5:0.8b...")
    tool = PhoneCameraTool()
    action = PhoneCameraVisionAction(
        question="Describe what you see in this camera frame."
    )
    result = tool.execute(action)
    print("Execution Success:", result.success)
    print("Tool Name:        ", result.tool_name)
    print("Bytes Captured:   ", result.output_payload.get("bytes_captured"))
    print("Spoken Output:    ", result.output_payload.get("speech_reply"))

if __name__ == "__main__":
    main()

