"""Compile editable Python policies. Only apply code you trust: this is not a sandbox."""
from pathlib import Path
from itertools import count
import sys
from types import ModuleType

_MODULE_IDS = count()


def default_policy_source():
    # This is the full Python module shown by the desktop editor and exported
    # with runs, not the earlier JavaScript template string.
    return Path(__file__).with_name("user_model.py").read_text(encoding="utf-8")


def compile_policy(source, settings=None, filename="<edited-policy>"):
    # Package context lets the supplied source keep its relative imports when
    # copied into an editor or saved under a different filename.
    name = f"bailey_motion.edited_policy_{next(_MODULE_IDS)}"
    module = ModuleType(name)
    module.__package__, module.__file__ = "bailey_motion", filename
    # Dataclasses and normal Python inspection expect the defining module to
    # exist in sys.modules. Successful modules stay alive with their policy code.
    sys.modules[name] = module
    namespace = module.__dict__
    try:
        # Compile/exec and factory construction execute trusted code normally.
        # Giving it a package context enables relative imports such as .config.
        exec(compile(source, filename, "exec"), namespace)
        factory = namespace.get("create_policy")
        # Prefer an explicit factory; support a directly defined UserModel too.
        if callable(factory):
            policy = factory(settings)
        elif callable(namespace.get("UserModel")):
            policy = namespace["UserModel"](settings)
        else:
            raise ValueError("Policy source must define create_policy(settings=None) or UserModel.")
        decide = policy.get("decide") if isinstance(policy, dict) else getattr(policy, "decide", None)
        # Other hooks are optional, but every usable policy must request motion.
        if not callable(decide):
            raise ValueError("Your model must implement decide(agent, api).")
        return policy
    except Exception:
        # Do not leave partially initialized modules registered after a failed edit.
        sys.modules.pop(name, None)
        raise
