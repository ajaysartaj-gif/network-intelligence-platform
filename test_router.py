from netmiko import ConnectHandler

router = {
    "device_type": "cisco_ios_telnet",
    "host": "127.0.0.1",
    "port": 5000,
}

try:
    conn = ConnectHandler(**router)

    output = conn.send_command("show ip interface brief")

    print("\n===== ROUTER OUTPUT =====\n")
    print(output)

    conn.disconnect()

except Exception as e:
    print(f"\nConnection failed: {e}")
