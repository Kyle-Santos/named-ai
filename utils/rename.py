import os

def append_name_low(directory):
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)

        # Skip directories
        if os.path.isdir(file_path):
            continue

        # Split the filename and extension
        name, ext = os.path.splitext(filename)
        new_name = f"dlsu_goks_cam_{name}{ext}"

        new_path = os.path.join(directory, new_name)
        os.rename(file_path, new_path)

        print(f'Renamed: "{filename}" → "{new_name}"')

if __name__ == "__main__":
    dir_path = "goks_cam_node/captures"
    if os.path.isdir(dir_path):
        append_name_low(dir_path)
        print("✅ All files have been renamed.")
    else:
        print("❌ Invalid directory path.")
