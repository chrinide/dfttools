"""
This submodule contains commonly used shortcuts to parse the data.
"""
import inspect

import numericalunits

import parsers
    
from parsers.generic import AbstractParser, ParseError

def tag_method(*tags, **kwargs):
    """
    A generic decorator tagging some method.
    
    Kwargs:
    
        take_file (bool): set to True and the File object will be passed
        to this method.
    """
    take_file = kwargs.get("take_file", False)
    
    def f_w(func):
        
        if "__tags__" in dir(func):
            func.__tags__ += list(tags)
        else:
            func.__tags__ = list(tags)
        
        func.__take_file__ = take_file
        
        if len(tags)>0 and not (func.__doc__ is None):
            func.__doc__ += """
    .. note::
    
        This method can be shortcut """ + (", ".join("``dfttools.simple.parse(file,\""+i+"\")``" for i in tags)) + ".\n"
        
        return func
        
    return f_w
    
band_structure = tag_method("band-structure")
unit_cell = tag_method("unit-cell")

def get_all_parsers(*modules):
    """
    Retrieves all parsers.
    
    Kwargs:
    
        modules (list): a list of names of ``parsers`` submodules to
        search at.
        
    Returns:
    
        A list of parsing classes.
    """
    
    parsers.__import_all_parsers__()
    
    if len(modules) == 0:
        modules = []
        for name in dir(parsers):
            obj = getattr(parsers, name)
            if inspect.ismodule(obj):
                modules.append(name)
    result = []
    
    for name in modules:
        module = getattr(parsers, name)
        for obj_name in dir(module):
            obj = getattr(module, obj_name)
            if inspect.isclass(obj) and issubclass(obj, AbstractParser) and not obj == AbstractParser and not obj in result:
                result.append(obj)
                
    return result
    
def guess_parser(f):
    """
    Guesses parsers for a given data.
    
    Args:
    
        f (file): a file to parse.
        
    Returns:
    
        A list of parser candidates.
    """
    result = []
    
    # Guess by contents
    f.seek(0)
    header = f.read(1024*1024)
    for parser_class in get_all_parsers():
        try:
            if parser_class.valid_header(header):
                result.append(parser_class)
        except NotImplementedError:
            pass
    f.seek(0)
            
    # Guess by name
    if "name" in dir(f) and isinstance(f.name, str):
        for parser_class in get_all_parsers():
            try:
                if parser_class.valid_filename(f.name):
                    result.append(parser_class)
            except NotImplementedError:
                pass
            
    return result
    
def parse(f, tag, *args):
    """
    Identifies and parses data.
    
    Args:
    
        f (file): a file to parse;
        
        tag (str): the data tag, such as ``unit-cell`` or
        ``band-structure``;
        
    Returns:
    
        The parsed data.
    """
    candidates = guess_parser(f)
    debug_data = "Candidate classes:\n" + "\n".join(" - "+str(i) for i in candidates)
    
    if len(candidates) == 0:
        raise ParseError("Unidentified data: no parser match")
    
    data = f.read()
    
    attempted = []
    
    for parser_class in candidates:
        parser = parser_class(data)
        for a in dir(parser):
            attr = getattr(parser, a)
            if "__tags__" in dir(attr) and tag in attr.__tags__:
                try:
                    
                    attempted.append(parser.__class__.__name__+"."+attr.__name__)
                    if attr.__take_file__:
                        return attr(f, *args)
                    else:
                        return attr(*args)
                        
                except (StopIteration, ParseError):
                    pass
    
    if len(attempted) == 0:
        raise ParseError("No matching parser found\n"+debug_data)
    
    else:
        raise ParseError("Parsing failed, attempted following candidates:\n" + "\n".join(tuple(
            " - "+i for i in cadidates
        )))
