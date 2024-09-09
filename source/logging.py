import logging

class LogWrapper():

    def __init__(self):

        logging.basicConfig(level=logging.INFO)
        # formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logging.info('Testing')

