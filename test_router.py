from netmiko import ConnectHandler

# --- CONFIGURATION ---
# Check your Mac Terminal right now to see if these values changed!
PINGGY_HOST = "emoqe-203-145-57-1.run.pinggy-free.link"
PINGGY_PORT = 42093 

router = {
    "device_type": "cisco_ios",
    "host": PINGGY_HOST,
    "port": PINGGY_PORT,
    "username": "admin",
    "password": "admin",
    "timeout": 90,
    "auth_timeout": 90,
    "fast_cli": False,
}

def run_test():
    try:
        print(f"Connecting to {PINGGY_HOST}:{PINGGY_PORT}...")
        
        # We no longer pass ssh_config_dict here
        conn = ConnectHandler(**router)
        
        print("Connected! Fetching data...")
        output = conn.send_command("show ip interface brief")
        
        print("\n" + "="*40)
        print(output)
        print("="*40)
        
        conn.disconnect()
        print("\nSuccess.")

    except Exception as e:
        print(f"\n[ERROR]: {e}")

if __name__ == "__main__":
    run_test()