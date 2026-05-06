import os
import importlib
import inspect
import sys

# Get current directory
_current_dir = os.path.dirname(__file__)

# Dynamically import all server modules from subdirectories
for _item in sorted(os.listdir(_current_dir)):
    _item_path = os.path.join(_current_dir, _item)
    if os.path.isdir(_item_path) and not _item.startswith('_'):
        try:
            # Look for .py files in this directory (excluding __init__.py)
            for _file in sorted(os.listdir(_item_path)):
                if _file.endswith('.py') and _file != '__init__.py':
                    _module_name = _file[:-3]  # Remove .py extension
                    try:
                        # Import the specific module
                        _module = importlib.import_module(f'.{_item}.{_module_name}', package=__name__)

                        # Get all classes defined in the module
                        for _name, _obj in inspect.getmembers(_module, inspect.isclass):
                            # Only import classes defined in this module (not imported from elsewhere)
                            if _obj.__module__.startswith(f'{__name__}.{_item}'):
                                globals()[_name] = _obj
                    except ImportError as _e:
                        print(f"Warning: Failed to import {_item}.{_module_name}: {_e}", file=sys.stderr)
                    except Exception as _e:
                        print(f"Warning: Error processing {_item}.{_module_name}: {_e}", file=sys.stderr)
        except Exception as _e:
            print(f"Warning: Error processing directory {_item}: {_e}", file=sys.stderr)

# Clean up temporary variables
for _var in ['_current_dir', '_item', '_item_path', '_file', '_module_name', '_module', '_name', '_obj', '_e']:
    globals().pop(_var, None)