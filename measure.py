#!/usr/bin/env python

try:
    import os
    import json
    import logging
    import subprocess
    from datetime import datetime

    from pymongo import MongoClient
    import speedtest

except ImportError as e:
    print(f'Error occured during import: {e}')
    print('Please install all necessary libraries and try again')
    exit(1)


def get_logger(logger_name=__name__, 
        log_level=logging.DEBUG, 
        file_name='log.log', 
        file_format_str='%(asctime)s: %(levelname)s: %(name)s: %(message)s', 
        stream_format_str='%(asctime)s: %(levelname)s: %(name)s: %(message)s'):
    """
    Create a logger and return.

    Arguments:
        logger_name: name of the logger, by default is __name__
        log_level: threshold level of the logging, by default is DEBUG
        file_name: name of the logging file, by default is log.log
        file_format_str: format of the logs for files
        stream_format_str: format of the logs for stream
    Return:
        logger: the created logger
    """
    file_formatter = logging.Formatter(file_format_str)
    stream_formatter = logging.Formatter(stream_format_str)

    file_handler = logging.FileHandler(file_name)
    file_handler.setFormatter(file_formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(stream_formatter)

    logger = logging.getLogger(name=logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger

class SpeedTesting():
   
    def __init__(self, config_path):
        # Parse the config file
        self._config_path = config_path
        try:
            with(open(config_path, 'r')) as f:
                    self._configs = json.load(f)
        except Exception as e:
            print(f"An error occured while loading the config file: {e}")
            exit(1)

        self._logger = get_logger("SPEEDTEST_LOG", file_name=self._configs['log_file'])

        try:
            self.speedtest = speedtest.Speedtest()
            self._logger.info("Speedtest setup complete")
            speedtest_fail = False
        except Exception as e:
            self._logger.exception("Error while speedtest client creation")
            speedtest_fail = True

        try:
            self.setup_mongo()
            self._logger.info("Mongo setup done")
        except:
            self._logger.exception("Mongo setup failed")

        if speedtest_fail:
            res = speedtest.SpeedtestResults()
            res = self.process_results(res)
            self.add_to_queue([res])
        self.process_queue()
        
    def parse_wifi_name(self):
        try:
            out = subprocess.Popen("/sbin/iwgetid", stdout=subprocess.PIPE, shell=True)
            out, err = out.communicate()
            out = out.decode('utf-8')
            if err:
                self._logger.error(f"Error: {err}, content: {out}")
                wifi_name = out
            else:
                wifi_name = out.split('"')[1]
                self._logger.info("Wifi name parsed")
        except:
            self._logger.exception("Something wrong in wifi name parsing")
            wifi_name = None
        return wifi_name

    def measure(self):
        if not hasattr(self, 'speedtest'):
            self._logger.error("No speedtest client found")
            return
        self.check_both_speed()
        res = self.process_results()
        need_to_queue = self.insert_measurement(res)
        if need_to_queue:
            self._logger.info("Something wrong, inserting into queue")
            self.add_to_queue([res])
        else:
            self._logger.info("Measurement inserted succesfully")

    def process_queue(self):
        # if queue not empty, try to insert all files from 
        queue = self.check_queue()
        failed_again = []
        while queue:
            measurement = queue.pop()
            measurement['measured'] = datetime.strptime(measurement['measured'], self._configs['datetime_format'])
            self._logger.info("Queue ready to insert.")
            failed = self.insert_measurement(measurement)
            if failed:
                self._logger.info("Failed to insert, adding back to queue")
                failed_again.append(measurement)
        if failed_again:
            self._logger.info("Failed samples present, adding back to queue")
            self.add_to_queue(failed_again)
        
    def check_queue(self):
        if not os.path.exists(self._configs['queue_file']):
            self._logger.info("Queue empty")
            return None
        with open(self._configs['queue_file'], 'r') as f:
            queue = json.load(f)
        os.remove(self._configs['queue_file'])
        return queue

    def add_to_queue(self, measurements):
        queue = self.check_queue()
        if queue:
            queue.extend(measurements)
        else:
            queue = measurements
        self._logger.info("Dumping queue file")
        with open(self._configs['queue_file'], "w") as f:
            json.dump(queue, f, default=str)
            
    def setup_mongo(self):
        mongo_client = MongoClient(self._configs['connection_string'])
        speedtest_db = mongo_client[self._configs['db_name']]
        self.collection = speedtest_db[self._configs['collection_name']]
        self._logger.info("Connection to MongoDB established")

    def check_both_speed(self):
        try:
            self._logger.info("Checking download")
            self.speedtest.download()
        except Exception as e:
            self._logger.exception("Download failed")
        try:
            self._logger.info("Checking upload")
            self.speedtest.upload()
        except:
            self._logger.exception("Upload failed")

        self._logger.info("Results ready")

    def process_results(self, res=None):
        if res is None:
            res = self.speedtest.results.dict()
        else:
            res = res.dict()
        res['download_mb'] = res['download'] / 1000000
        res['upload_mb'] = res['upload'] / 1000000

        self._logger.info(f"\n\tDownload: {res['download_mb']}\n\tUpload: {res['upload_mb']}")

        res['measured'] = datetime.strptime(datetime.now().strftime(self._configs['datetime_format']), self._configs['datetime_format'])
        wifi_name = self.parse_wifi_name()
        res['wifi_name'] = wifi_name
        return res

    def insert_measurement(self, res):
        try:
            response = self.collection.insert_one(res)
            self._logger.info("Insertion successfull")
        except Exception as e:
            response = None

        if response:
            if response.acknowledged:
                self._logger.info("DB acknowledged")
                failed = False
            else:
                self._logger.info("DB not acknowledged, need to queue")
                failed = True
        else:
            self._logger.info("Not inserted into DB, need to queue")
            failed = True
        return failed


def main():
    config_path = "configs.json"
    sp = SpeedTesting(config_path)
    sp.measure()
    sp.process_queue()


if __name__ == "__main__":
    main()

