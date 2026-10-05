import torch
import onnxruntime as ort

def main():
    print("torch", torch.__version__)
    print("cuda_available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
    else:
        print("device", "cpu")
    print("cuda", torch.version.cuda)
    try:
        print("cudnn", torch.backends.cudnn.version())
    except Exception as e:
        print("cudnn", None, e)
    print("ort", ort.__version__)
    print("ort_providers", ort.get_available_providers())

if __name__ == "__main__":
    main()
