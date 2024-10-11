import colorama
import logging
import re

class LogWrapper():

    _configured = False

    @classmethod
    def get_logger(cls, name):
        if not cls._configured:
            cls._setup()
            cls._configured = True
        return logging.getLogger(name)

    @classmethod
    def _setup(cls):
        colorama.init(autoreset=True)
        formatter = cls.LogFormatter('%(asctime)s.%(msecs)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S')
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)

        logging.basicConfig(
            level=logging.INFO,
            handlers = [handler]
        )

        log = logging.getLogger('log')
        log.info(f'Logging service started')

    class LogFormatter(logging.Formatter):
        colors = {
            'b': colorama.Fore.BLUE,
            'c': colorama.Fore.CYAN,
            'g': colorama.Fore.GREEN,
            'm': colorama.Fore.MAGENTA,
            'r': colorama.Fore.RED,
            'y': colorama.Fore.YELLOW,
            'x': colorama.Fore.RESET,
        }

        levels = {
            'DEBUG': colors['g'],
            'INFO': colors['c'],
            'PROC': colors['c'],
            'WARNING': colors['y'],
            'ERROR': colors['r'],
            'CRITICAL': colors['r']
        }

        def format(self, record):
            reset = colorama.Fore.RESET + colorama.Style.RESET_ALL
            record.levelname = self.levels.get(record.levelname, "") + '[' + record.levelname +']' + reset
            record.msecs = str(int(record.msecs)).zfill(3)

            def colorizer(match):
                if match.group(1)[1] in self.colors:
                    color = self.colors[match.group(1)[1]]
                    return f'{color}{match.group(2)}{reset}'
                return match.group(2)

            pattern = r'(\$[a-z])\((.*?)\)'
            result = re.sub(pattern, colorizer, record.msg)
            record.msg = result

            message = super().format(record)
            return f'{message}'