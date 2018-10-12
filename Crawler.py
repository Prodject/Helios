import logging
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from Utils import params_from_str
import time
import json
import random
import string
import hashlib
import os
from Engine import CookieLib
import sys

try:
    import urlparse
    from Queue import Queue, Empty
except ImportError:
    import urllib.parse as urlparse
    from queue import Queue, Empty


# Main Crawler module, uses BeautifulSoup4 to extract url / form data

class Crawler:
    # checksum, array of possible values
    postdata = []
    max_allowed_checksum = 5

    max_urls = 200
    max_url_unique_keys = 1
    url_variations = []
    ignored = []

    max_postdata_per_url = 10
    max_postdata_unique_keys = 5
    allowed_filetypes = [None, '.php', '.aspx', '.asp', '.html', '.jsp', '.xhtml', '.htm']
    output_filename = "tmp.json"
    thread_count = 5
    cookie = CookieLib()
    is_debug = True
    logger = None
    headers = {}

    def __init__(self, base_url, agent=None):
        self.base_url = base_url
        self.root_url = '{}://{}'.format(urlparse.urlparse(self.base_url).scheme, urlparse.urlparse(self.base_url).netloc)
        self.pool = ThreadPoolExecutor(max_workers=10)
        self.scraped_pages = []
        self.to_crawl = Queue()
        self.to_crawl.put([self.base_url, None])
        self.output_filename = os.path.join('data', 'crawler_%s_%d.json' % (urlparse.urlparse(self.base_url).netloc, time.time()))
        self.logger = logging.getLogger("Crawler")
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(ch)
        self.logger.debug("Starting Crawler")
        if agent:
            self.headers['User-Agent'] = agent

    def get_filetype(self, url):
        url = url.split('?')[0]
        loc = urlparse.urlparse(url).path.split('.')
        if len(loc) is 1:
            return None
        return ".{0}".format(loc[len(loc)-1])

    def parse_links(self, html, rooturl):
        try:
            soup = BeautifulSoup(html, 'html.parser')
            links = soup.find_all('a', href=True)
            for link in links:
                if (self.to_crawl.qsize() + len(self.scraped_pages)) > self.max_urls:
                    continue
                url = link['href']
                url = url.split('#')[0]
                if link in self.ignored:
                    continue
                if self.get_filetype(url) not in self.allowed_filetypes:
                    self.ignored.append(url)
                    self.logger.debug("Url %s will be ignored because file type is not allowed" % url)
                    continue
                if "?" in url:
                    params = params_from_str(url.split('?')[1])
                    checksum = FormDataToolkit.get_checksum(params)
                    if [url, checksum] in self.url_variations:
                        var_num = 0
                        for part in self.url_variations:
                            if part == [url, checksum]:
                                var_num += 1
                        if var_num >= self.max_url_unique_keys:
                            self.ignored.append(url)
                            self.logger.debug("Url %s will be ignored because key variation limit is exceeded" % url)
                            continue
                        self.url_variations.append([url, checksum])
        except Exception as e:
            self.logger.warning("Parse error on %s -> %s" % (rooturl, e.message))


            # if local link or link on same site root
            if url.startswith('/') or url.startswith(self.root_url):
                url = urlparse.urljoin(rooturl, url)
                if [url, None] not in self.scraped_pages:
                    self.to_crawl.put([url, None])
            # javascript, raw data, mailto etc..
            if ':' not in url:
                url = urlparse.urljoin(rooturl, url)
                if [url, None] not in self.scraped_pages:
                    self.to_crawl.put([url, None])

    def get_col(self, arr, col):
        return map(lambda x: x[col], arr)

    def scrape_info(self, html, rooturl):
        e = Extractor(html, rooturl)
        forms = e.extract(fill_empty=True)
        for f in forms:
            url, data = f
            checksum = FormDataToolkit.get_checksum(data)
            if checksum not in self.get_col(self.postdata, 0):
                if [url, data] not in self.scraped_pages:
                    self.to_crawl.put([url, data])
                self.postdata.append([checksum, url, data])

    def post_scrape_callback(self, res):
        result = res.result()
        if result and result.status_code == 200:
            self.parse_links(result.text, result.url)
            self.scrape_info(result.text, result.url)
            try:
                self.cookie.autoparse(result.headers)
            except Exception as e:
                print(e.message)

    def scrape_page(self, url):
        url, data = url
        try:
            res = requests.get(url, timeout=(3, 30), cookies=self.cookie.cookies, allow_redirects=False, headers=self.headers) if not data else requests.post(url, data, cookies=self.cookie.cookies, allow_redirects=False,  timeout=(3, 30))
            return res
        except requests.RequestException:
            return
        except Exception as e:
            self.logger.warning("Error in thread: %s" % e.message)

    def has_page(self, url, data):
        for u, d in self.scraped_pages:
            if url == u and data == d:
                return True
        return False

    def run_scraper(self):
        emptyrun = 0
        while True:
            try:
                target_url = self.to_crawl.get(timeout=10)
                if not self.has_page(target_url[0], target_url[1]):
                    self.logger.info("Scraping URL: {}".format(target_url))
                    self.scraped_pages.append([target_url[0], target_url[1]])
                    job = self.pool.submit(self.scrape_page, target_url)
                    job.add_done_callback(self.post_scrape_callback)
                    emptyrun += 1
            except Empty:
                return
            except Exception as e:
                self.logger.warning("Error: %s" % e.message)
                continue
            self.logger.info("Todo: {0} Done: {1}".format(self.to_crawl.qsize(), len(self.scraped_pages)))
            output = json.dumps(self.scraped_pages)
            with open(self.output_filename, 'w') as f:
                f.write(output)


# class with some static methods
class FormDataToolkit:
    def __init__(self):
        pass

    @staticmethod
    def get_checksum(data):
        keys = []
        for x in data:
            keys.append(x)
        return hashlib.md5(''.join(keys)).hexdigest()

    @staticmethod
    def get_full_checksum(data):
        keys = []
        for x in data:
            keys.append("{0}={1}".format(x, data[x]))
        return hashlib.md5('&'.join(keys)).hexdigest()

# the Extractor class is used to extract forms from HTML
# the default extract() method is equipped with the functionality to automatically fill in input fields
# dunno if textarea works :)
class Extractor:
    body = None
    url = None
    random_text_size = 8
    user_email = None
    user_password = None

    def __init__(self, text, original_url = ""):
        soup = BeautifulSoup(text, 'html.parser')
        self.body = soup
        self.url = original_url

    def extract(self, fill_empty=False):
        rtn = []
        for form in self.get_forms():
            action = self.get_action(form)
            inputs = self.get_inputs(form)
            data = self.get_form_parameters(inputs, fill_empty)
            rtn.append([urlparse.urljoin(self.url, action), data])
        return rtn

    def get_form_parameters(self, inputs, fill_empty):
        res = {}
        for inp in inputs:
            try:
                name = inp['name']
                input_type = inp['type'] if 'type' in inp.attrs else None

                value = None
                if 'value' in inp.attrs and len(inp['value']) > 0:
                    value = inp['value']
                elif fill_empty and input_type != "hidden":
                    value = self.generate_random(input_type, name)
                else:
                    value = ""
                if name not in res:
                    res[name] = value
            except:
                pass
        return res

    def generate_random(self, input_type, name):
        if not input_type:
            return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(self.random_text_size))
        if input_type == "email" or "mail" in name:
            if not self.user_email:
                self.user_email = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(self.random_text_size)) + '@' + ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(self.random_text_size)) + '.com'
            return self.user_email
        if input_type in ['number', 'integer', 'decimal']:
            return 1
        return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(self.random_text_size))

    def get_inputs(self, form):
        inputs = form.find_all('input', {'name': True})
        inputs.extend(form.find_all('textarea', {'name': True}))
        return inputs

    def get_action(self, form):
        if 'action' not in form.attrs:
            return self.url
        return urlparse.urljoin(self.url, form['action'])

    def get_forms(self):
        forms = []
        try:
            forms = self.body.find_all('form')
        except:
            return forms
        return forms