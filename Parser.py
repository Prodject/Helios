import os
import json
from Engine import MatchObject, CustomRequestBuilder, RequestBuilder
from Utils import has_seen_before, response_to_dict
import sys
import logging
try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse


class ScriptEngine:
    scripts_active = []
    scripts_fs = []
    scripts_passive = []
    results = []
    triggers = []
    can_fs = True
    can_exploit = True
    s = None

    def __init__(self):
        self.logger = self.logger = logging.getLogger("ScriptEngine")
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(ch)
        self.logger.debug("Starting script parser")
        self.parse_scripts()

    def parse_scripts(self):
        self.s = ScriptParser()
        self.s.load_scripts()
        self.scripts_active = []
        self.scripts_fs = []
        self.scripts_passive = []

        for script in self.s.scripts:
            matches = []
            for x in script['matches']:
                mobj = MatchObject(
                    mtype=x['type'],
                    match=x['match'],
                    location=x['location'],
                    name=x['name'] if 'name' in x else script['name'],
                    options=list(x['options'])
                )
                matches.append(mobj)
            scriptdata = {
                "name": script['name'],
                "find": script['find'],
                "request": script['request'],
                "data": script['data'] if 'data' in script else {},
                "matches": matches
            }
            if not script['request']:
                if script['run_at'] == "response":
                    self.scripts_passive.append(scriptdata)
                if script['run_at'] == "fs":
                    self.scripts_fs.append(scriptdata)

            if script['request']:
                self.scripts_active.append(scriptdata)

    def run_fs(self, base_url):
        links = []
        if self.can_fs:
            for script in self.scripts_fs:
                if str(script['find']) == "once":
                    if has_seen_before(script['name'], self.results):
                        continue
                data = script['data']
                new_req = CustomRequestBuilder(
                    url=data['url'],
                    data=data['data'] if 'data' in data else None,
                    headers=data['headers'] if 'headers' in data else {},
                    options=data['options'] if 'options' in data else [],
                )
                new_req.root_url = base_url
                result = new_req.run()
                if result:
                    # is found so added to crawler
                    if result.response.code == 200:
                        links.append([urlparse.urljoin(base_url, new_req.url), new_req.data])
                    for match in script['matches']:
                        mresult = match.run(result.response)
                        if mresult:
                            res = "%s [%s] > %s" % (script['name'], result.response.to_string(), mresult)
                            self.logger.info("Discovered: %s" % res)
                            self.results.append({"script": script['name'], "match": mresult, "data": response_to_dict(result.response)})
            return links

    def run_scripts(self, request):
        for script in self.scripts_passive:
            if str(script['find']) == "once":
                if has_seen_before(script['name'], self.results):
                    continue
            for match in script['matches']:
                result = match.run(request.response)
                if result:
                    res = "%s [%s] > %s" % (script['name'], request.response.to_string(), result)
                    self.logger.info("Discovered: %s" % res)
                    self.results.append(
                        {"script": script['name'], "match": result, "data": response_to_dict(request.response)})
        if self.can_exploit:
            for script in self.scripts_active:
                r = RequestBuilder(
                    req=request,
                    inject_type=script['request'],
                    inject_value=script['data']['inject_value'],
                    matchobject=script['matches'],
                    name=script['name']
                )
                results = r.run()
                if results:
                    for r in results:
                        if r not in self.results:
                            res = "[%s] URL %s > %s" % (script['name'], r['data']['request']['url'], r['match'])
                            self.logger.info("Discovered: %s" % res)
                            self.results.append(r)


class ScriptParser:
    directory = 'scripts'
    root_dir = ''
    script_dir = ''
    scripts = []
    logger = None

    def __init__(self, newdir=None):
        self.root_dir = os.path.dirname(os.path.realpath(__file__))
        self.script_dir = os.path.join(self.root_dir, self.directory) if not newdir else newdir
        self.logger = logging.getLogger("ScriptParser")
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(ch)
        if not os.path.isdir(self.script_dir):
            self.logger.error("Cannot initialise script engine, directory '%s' does not exist" % self.script_dir)
        self.scripts = []

    def load_scripts(self):
        self.logger.debug("Init script engine")
        for f in os.listdir(self.script_dir):
            script = os.path.join(self.script_dir, f)
            if os.path.isfile(script):
                try:
                    with open(script, 'r') as scriptfile:
                        data = scriptfile.read()
                    jsondata = json.loads(data)
                    self.scripts.append(jsondata)
                except ValueError:
                    self.logger.error("Script %s appears to be invalid JSON, ignoring" % f)
                    pass
                except IOError:
                    self.logger.error("Unable to access script file %s, ignoring" % f)
                    pass
        self.logger.info("Script Engine loaded %d scripts" % len(self.scripts))