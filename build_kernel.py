import argparse
import subprocess
import os
import shutil
import re
from datetime import datetime
import zipfile

class CommandError(Exception):
    pass

def run_command(command, stdout_log_file=None, stderr_log_file=None):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    stdout = stdout.decode("utf-8")
    stderr = stderr.decode("utf-8")
    if stdout_log_file:
        with open(stdout_log_file, "w") as f:
            f.write(stdout)
    if stderr_log_file:
        with open(stderr_log_file, "w") as f:
            f.write(stderr)
    if stdout_log_file or stderr_log_file:
        print(f"Output log files: {stdout_log_file}, {stderr_log_file}")
    if process.returncode != 0:
        raise CommandError(f"Command failed: {command}. Exit code: {process.returncode}")
    return stdout, stderr

def file_exists(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return False
    return True

def extract_match(regex, text):
    match = re.search(regex, text)
    if not match:
        raise AssertionError(f'Failed to match pattern: {pattern} with regex: {regex}')
    return match.group(1)

def display_info(info_dict):
    print('================================')
    for key, value in info_dict.items():
        print(f"{key}={value}")
    print('================================')

def create_zip(zip_filename, files):
    print(f"Creating zip: {zip_filename} with {len(files)} files")
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in files:
            zf.write(file)
    print("Zip creation complete")

class ClangCompiler:
    @staticmethod
    def verify_executable():
        try:
            run_command(['./toolchain/bin/clang', '-v'])
        except CommandError:
            print("Clang execution failed")
            raise
    
    @staticmethod
    def get_version():
        version_regex = r"(.*?clang version \d+(\.\d+)*)"
        _, stderr_output = run_command(['./toolchain/bin/clang', '-v'])
        return extract_match(version_regex, stderr_output)

def main():
    parser = argparse.ArgumentParser(description="Build Kernel with specified arguments")
    parser.add_argument('--target', type=str, required=True, help="Target device (a51/m21/...)")
    parser.add_argument('--allow-dirty', action='store_true', help="Allow dirty build")
    parser.add_argument('--oneui', action='store_true', help="OneUI build")
    parser.add_argument('--aosp', action='store_true', help="AOSP build (Default)")
    parser.add_argument('--no-ksu', action='store_true', help="Don't include KernelSU support in kernel")
    parser.add_argument('--permissive', action='store_true', help="Use SELinux permissive mode")
    args = parser.parse_args()

    if args.oneui and args.aosp:
        print("Both OneUI and AOSP flags cannot be defined at the same time.")
        return
    
    valid_targets = ['a51', 'f41', 'm31s', 'm31', 'm21', 'gta4xl', 'gta4xlwifi']
    if args.target not in valid_targets:
        print("Specify a valid target: a51/f41/m31s/m31/m21/gta4xl/gta4xlwifi")
        return

    common_flags = [
        'CROSS_COMPILE=aarch64-linux-gnu-', 'CC=clang', 'LD=ld.lld', 
        'AS=llvm-as', 'AR=llvm-ar', 'OBJDUMP=llvm-objdump', 
        'READELF=llvm-readelf', 'NM=llvm-nm', 'OBJCOPY=llvm-objcopy', 
        'ARCH=arm64', f'-j{os.cpu_count()}'
    ]
 
    kernel_version = "1.7.0"

    if not file_exists("AnyKernel3/anykernel.sh"):
        run_command(['git', 'submodule', 'update', '--init'])
    if not file_exists("toolchain/bin/clang"):
        print(f"Toolchain must be available at {os.getcwd()}/toolchain")
        return
    
    ClangCompiler.verify_executable()
    
    build_type = "OneUI" if args.oneui else "AOSP"
    selinux_state = "Permissive" if args.permissive else "Enforcing"
    display_info({
        'Kernel Name': 'Something New',
        'Kernel Version': kernel_version,
        'Build Type': build_type,
        'SELinux': selinux_state,
        'Device': args.target,
        'With KernelSU': not args.no_ksu,
        'Using LLVM': True,
        'Toolchain Version': ClangCompiler.get_version(),
    })
    
    toolchain_path = os.path.join(os.getcwd(), 'toolchain', 'bin')
    if toolchain_path not in os.environ['PATH'].split(os.pathsep):
        os.environ["PATH"] = toolchain_path + ':' + os.environ["PATH"]
    
    output_dir = 'out'
    if os.path.exists(output_dir) and not args.allow_dirty:
        print('Cleaning build output...')
        shutil.rmtree(output_dir)
    
    make_common = ['make', 'O=out', 'LLVM=1', f'-j{os.cpu_count()}'] + common_flags
    make_defconfig = make_common + [f'exynos9611-{args.target}_defconfig']
    
    if args.oneui:
        make_defconfig += ['oneui.config']
    if args.permissive:
        make_defconfig += ['permissive.config']
    make_defconfig += ['no-ksu.config']

    start_time = datetime.now()
    print('Running make defconfig...')
    run_command(make_defconfig, stdout_log_file="make_defconfig_stdout.log", stderr_log_file="make_defconfig_stderr.log")
    print('Building the kernel...')
    run_command(make_common, stdout_log_file="make_common_stdout.log", stderr_log_file="make_common_stderr.log")
    print('Build complete')
    elapsed_time = datetime.now() - start_time
    
    with open(os.path.join(output_dir, 'include', 'generated', 'utsrelease.h')) as f:
        kernel_version_info = extract_match(r'"([^"]+)"', f.read())
    
    shutil.copyfile('out/arch/arm64/boot/Image', 'AnyKernel3/Image')
    zip_filename = 'SN_{}_{}_{}_{}.zip'.format(
        kernel_version, args.target, 'OneUI' if args.oneui else 'AOSP', datetime.today().strftime('%Y-%m-%d'))
    os.chdir('AnyKernel3/')
    create_zip(zip_filename, [
        'Image', 
        'META-INF/com/google/android/update-binary',
        'META-INF/com/google/android/updater-script',
        'tools/ak3-core.sh',
        'tools/busybox',
        'tools/magiskboot',
        'anykernel.sh',
        'version'
    ])
    final_zip_path = os.path.join(os.getcwd(), '..', zip_filename)
    try:
        os.remove(final_zip_path)
    except FileNotFoundError:
        pass
    shutil.move(zip_filename, final_zip_path)
    os.chdir('..')
    display_info({
        'OUT_ZIPNAME': zip_filename,
        'KERNEL_VERSION': kernel_version_info,
        'ELAPSED_TIME': f"{elapsed_time.total_seconds()} seconds"
    })
    
if __name__ == '__main__':
    main()
