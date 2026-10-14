"""本地运行的进程级缓存互斥；进程退出后操作系统自动释放锁。"""

from contextlib import contextmanager
import os


class TokenCacheBusy(RuntimeError):
    pass


@contextmanager
def cache_lock(data_path):
    lock_path = data_path.with_name(data_path.name + '.lock')
    with open(lock_path, 'a+b') as file:
        if os.name == 'nt':
            import msvcrt
            if file.tell() == 0:
                file.write(b'0')
                file.flush()
            file.seek(0)
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise TokenCacheBusy('另一个进程正在使用凭据缓存，请稍后重试') from None
        else:
            import fcntl
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TokenCacheBusy('另一个进程正在使用凭据缓存，请稍后重试') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
