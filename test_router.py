from netmiko import ConnectHandler
import paramiko

# --- !!! CRITICAL: THE ENCRYPTION BYPASS !!! ---
# This part is why your previous attempt failed. 
# We must re-enable the older algorithms for your Cisco router.
paramiko.Transport._preferred_kex = (
    'diffie-hellman-group14-sha1',
    'diffie-hellman-group-exchange-sha1',
    'diffie-hellman-group1-sha1',
)
paramiko.Transport._preferred_ciphers = (
    'aes128-cbc',
    'aes192-cbc',
    'aes256-cbc',
)

# --- CONFIGURATION ---
# Updated with your new active tunnel details
PINGGY_HOST = "ugtft-203-145-57-1.run.pinggy-free.link"
PINGGY_PORT = 37459

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
        
        # ConnectHandler now uses the forced algorithms defined above
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
        print("\nNote: Ensure your Mac terminal still shows the tunnel is active.")

if __name__ == "__main__":
    run_test()