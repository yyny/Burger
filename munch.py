#!/usr/bin/env python
# -*- coding: utf8 -*-
"""
Copyright (c) 2011 Tyler Kenendy <tk@tkte.ch>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import os
import sys
import getopt
import urllib
import traceback

try:
    import json
except ImportError:
    import simplejson as json

from collections import deque

from jawa.classloader import ClassLoader
from jawa.transforms import simple_swap, expand_constants

from burger import website
from burger.roundedfloats import transform_floats


def import_toppings():
    """
    Attempts to imports either a list of toppings or, if none were
    given, attempts to load all available toppings.
    """
    this_dir = os.path.dirname(__file__)
    toppings_dir = os.path.join(this_dir, "burger", "toppings")
    from_list = []

    # Traverse the toppings directory and import everything.
    for root, dirs, files in os.walk(toppings_dir):
        for file_ in files:
            if not file_.endswith(".py"):
                continue
            elif file_.startswith("__"):
                continue
            elif file_ == "topping.py":
                continue

            from_list.append(file_[:-3])

    from burger.toppings.topping import Topping
    toppings = {}
    last = Topping.__subclasses__()

    for topping in from_list:
        __import__("burger.toppings.%s" % topping)
        current = Topping.__subclasses__()
        subclasses = list([o for o in current if o not in last])
        last = Topping.__subclasses__()
        if len(subclasses) == 0:
            print("Topping '%s' contains no topping" % topping)
        elif len(subclasses) >= 2:
            print("Topping '%s' contains more than one topping" % topping)
        else:
            toppings[topping] = subclasses[0]

    return toppings

if __name__ == "__main__":
    try:
        opts, args = getopt.gnu_getopt(
            sys.argv[1:],
            "t:o:vd:Dlc",
            [
                "toppings=",
                "output=",
                "verbose",
                "download=",
                "download-latest",
                "list",
                "compact",
                "url="
            ]
        )
    except getopt.GetoptError as err:
        print(str(err))
        sys.exit(1)

    # Default options
    toppings = None
    output = sys.stdout
    verbose = False
    download_jars = []
    download_latest = False
    list_toppings = False
    compact = False
    url = None

    for o, a in opts:
        if o in ("-t", "--toppings"):
            toppings = a.split(",")
        elif o in ("-o", "--output"):
            output = open(a, "w")
        elif o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-c", "--compact"):
            compact = True
        elif o in ("-d", "--download"):
            download_jars.append(a)
        elif o in ("-D", "--download-latest"):
            download_latest = True
        elif o in ("-l", "--list"):
            list_toppings = True
        elif o in ("-s", "--url"):
            url = a

    # Load all toppings
    all_toppings = import_toppings()

    # List all of the available toppings,
    # as well as their docstring if available.
    if list_toppings:
        for topping in all_toppings:
            print("%s" % topping)
            if all_toppings[topping].__doc__:
                print(" -- %s\n" % all_toppings[topping].__doc__)
        sys.exit(0)

    # Get the toppings we want
    if toppings is None:
        loaded_toppings = all_toppings.values()
    else:
        loaded_toppings = []
        for topping in toppings:
            if topping not in all_toppings:
                print("Topping '%s' doesn't exist" % topping)
            else:
                loaded_toppings.append(all_toppings[topping])

    class DependencyNode:
        def  __init__(self, topping):
            self.topping = topping
            self.provides = topping.PROVIDES
            self.depends = topping.DEPENDS
            self.childs = []

        def __repr__(self):
            return str(self.topping)

    # Order topping execution by building dependency tree
    topping_nodes = []
    topping_provides = {}
    for topping in loaded_toppings:
        topping_node = DependencyNode(topping)
        topping_nodes.append(topping_node)
        for provides in topping_node.provides:
            topping_provides[provides] = topping_node

    # Include missing dependencies
    for topping in topping_nodes:
        for dependency in topping.depends:
            if not dependency in topping_provides:
                for other_topping in all_toppings.values():
                    if dependency in other_topping.PROVIDES:
                        topping_node = DependencyNode(other_topping)
                        topping_nodes.append(topping_node)
                        for provides in topping_node.provides:
                            topping_provides[provides] = topping_node

    # Find dependency childs
    for topping in topping_nodes:
        for dependency in topping.depends:
            if not dependency in topping_provides:
                print("(%s) requires (%s)" % (topping, dependency))
                sys.exit(1)
            if not topping_provides[dependency] in topping.childs:
                topping.childs.append(topping_provides[dependency])

    # Run leaves first
    to_be_run = []
    while len(topping_nodes) > 0:
        stuck = True
        for topping in topping_nodes:
            if len(topping.childs) == 0:
                stuck = False
                for parent in topping_nodes:
                    if topping in parent.childs:
                        parent.childs.remove(topping)
                to_be_run.append(topping.topping)
                topping_nodes.remove(topping)
        if stuck:
            print("Can't resolve dependencies")
            sys.exit(1)

    jarlist = args

    # Download any jars that have already been specified
    for version in download_jars:
        client_path = website.client_jar(version, verbose)
        jarlist.append(client_path)

    # Download a copy of the latest snapshot jar
    if download_latest:
        client_path = website.latest_client_jar(verbose)
        jarlist.append(client_path)

    # Download a JAR from the given URL
    if url:
        url_path = urllib.urlretrieve(url)[0]
        jarlist.append(url_path)

    summary = []

    for path in jarlist:
        classloader = ClassLoader(path, max_cache=0, bytecode_transforms=[simple_swap, expand_constants])
        names = classloader.path_map.keys()
        num_classes = sum(1 for name in names if name.endswith(".class"))

        aggregate = {
            "source": {
                "file": path,
                "classes": num_classes,
                "other": len(names),
                "size": os.path.getsize(path)
            }
        }

        available = []
        for topping in to_be_run:
            missing = [dep for dep in topping.DEPENDS if dep not in available]
            if len(missing) != 0:
                if verbose:
                    print("Dependencies failed for %s: Missing %s" % (topping, missing))
                continue

            orig_aggregate = aggregate.copy()
            try:
                topping.act(aggregate, classloader, verbose)
                available.extend(topping.PROVIDES)
            except:
                aggregate = orig_aggregate # If the topping failed, don't leave things in an incomplete state
                if verbose:
                    print("Failed to run %s" % topping)
                    traceback.print_exc()

        summary.append(aggregate)

    def check(o, path=[]):
        import six
        if not isinstance(o, (str, int, float, dict, list, tuple)):
            print("Unknown value in final output: %s -- %s" % ('.'.join([ str(i) for i in path ]), repr(o)))
        if isinstance(o, dict):
            for k,v in six.iteritems(o):
                check(v, path=[*path, k])
        elif isinstance(o, (list, tuple)):
            for i,v in enumerate(o):
                check(v, path=[*path, i])
        return o

    check(summary)
    if not compact:
        json.dump(transform_floats(summary), output, sort_keys=True, indent=4)
    else:
        json.dump(transform_floats(summary), output)

    # Cleanup temporary downloads (the URL download is temporary)
    if url:
        os.remove(url_path)
    # Cleanup file output (if used)
    if output is not sys.stdout:
        output.close()
