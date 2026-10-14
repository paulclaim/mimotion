"""通过环境变量/交互输入密钥，在本机解密导出配置或 token 缓存。"""

import argparse
import getpass
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from util import aes_help


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ciphertext', nargs='?', help='Base64 密文；未提供时从标准输入读取')
    parser.add_argument('--mode', choices=('inspect', 'token'), default='inspect')
    parser.add_argument('--file', type=Path, help='读取密文文件；token 模式为原始二进制缓存')
    args = parser.parse_args()
    environment_key = 'INSPECT_AES_KEY' if args.mode == 'inspect' else 'AES_KEY'
    key = (os.environ.get(environment_key) or getpass.getpass(f'{environment_key}: ')).encode('utf-8')
    try:
        if args.file:
            data = args.file.read_bytes()
        else:
            data = (args.ciphertext or sys.stdin.read()).strip().encode('utf-8')
        if args.mode == 'inspect':
            data = aes_help.base64_to_bytes(data.decode('utf-8'))
            plain = aes_help.decrypt_data(data, key, key)
        else:
            if not args.file:
                data = aes_help.base64_to_bytes(data.decode('utf-8'))
            plain = aes_help.decrypt_token_data(data, key)
        print(plain.decode('utf-8'))
        return 0
    except (OSError, ValueError, TypeError, UnicodeError):
        print('解密失败，请检查密钥、密文格式和 --mode', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
