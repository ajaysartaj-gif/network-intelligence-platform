def seed_database():
    return True


def get_devices():
    return [
        {
            "hostname": "CORE-RTR-01",
            "ip": "10.0.0.1",
            "vendor": "Cisco",
            "role": "Core Router",
            "site": "HQ",
            "status": "up",
            "cpu": 45,
            "memory": 62,
        }
    ]


def get_incidents(status=None):
    return []


def get_changes():
    return []


def get_auto_actions():
    return []


def update_record(*args, **kwargs):
    return True


def add_device(*args, **kwargs):
    return True


def add_incident(*args, **kwargs):
    return True


def write_audit(*args, **kwargs):
    return True


def get_audit_logs(limit=100):
    return []
