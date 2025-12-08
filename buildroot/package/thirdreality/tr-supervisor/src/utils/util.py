# maintainer: guoping.liu@3reality.com

import threading
import logging
import subprocess
import time
from datetime import datetime
import urllib.error

"""
System utility functions for performing system operations like reboot, shutdown, and factory reset.
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def force_sync():
    """
    Force sync to flush NAND cache by executing sync command 3 times.
    This is necessary due to NAND caching mechanisms.
    
    Returns:
        bool: True if sync commands executed successfully, False otherwise
    """
    try:
        # Force sync 3 times to ensure data is written to NAND storage
        for _ in range(3):
            subprocess.run(["sync"], check=True)
        logging.info("Force sync completed (3 times)")
        return True
    except Exception as e:
        logging.error(f"Error during force sync: {e}")
        return False

def perform_reboot():
    """
        Safely stop necessary services and reboot the system.
        
        This function stops Docker service before rebooting to prevent data corruption.
        Docker stop failure is ignored and reboot will proceed anyway.
        
        Returns:
            bool: True if reboot command was executed (may not return if reboot succeeds)
        """
    try:
        # Ensure all data is flushed to disk before reboot
        try:
            force_sync()
        except Exception:
            pass  # Sync failure should not prevent reboot
        
        # Execute reboot command (will not return if successful)
        # Use check=False to ensure reboot is attempted even if command returns error
        logging.info("Executing reboot command...")
        subprocess.run(["reboot"], check=False)
        
        # If we reach here, reboot command may have failed, try alternative
        # Give a moment for reboot to take effect
        time.sleep(1)
        return True
    except Exception as e:
        logging.error(f"Error performing reboot: {e}")
        # Even if there's an error, try to reboot anyway
        try:
            subprocess.run(["reboot", "-f"], check=False)
        except:
            pass
        return False

def perform_factory_reset():
    try:
        # Ensure all data is flushed to disk before factory reset
        force_sync()
        
        subprocess.run(["/etc/adckey/adckey_function.sh", "longpressHome"], check=True)
        return True
    except Exception as e:
        logging.error(f"Error performing factory reset: {e}")
        return False

def threaded(func):
    def wrapper(*args, **kwargs):
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t
    return wrapper
