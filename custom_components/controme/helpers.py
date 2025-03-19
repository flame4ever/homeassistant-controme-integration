"""Helper functions for Controme integration."""
import asyncio
import logging
from typing import List, Dict, Any, Optional, Set
import socket
import aiohttp
import async_timeout
from ipaddress import IPv4Network, IPv4Address, IPv4Interface

_LOGGER = logging.getLogger(__name__)

def get_local_ip() -> Optional[str]:
    """Get the local IP address of the machine."""
    try:
        # Create a socket and connect to a known public address
        # This won't actually establish a connection but gives us the local IP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
        sock.close()
        _LOGGER.debug("Local IP detected: %s", local_ip)
        return local_ip
    except Exception as err:
        _LOGGER.error("Error getting local IP: %s", err)
        return None

def get_network_from_ip(ip: str) -> Optional[str]:
    """Get the network address from an IP address."""
    try:
        # Assume a /24 network
        interface = IPv4Interface(f"{ip}/24")
        network_str = str(interface.network)
        _LOGGER.debug("Network determined from IP %s: %s", ip, network_str)
        return network_str
    except Exception as err:
        _LOGGER.error("Error determining network from IP %s: %s", ip, err)
        return None

async def test_controme_host(session: aiohttp.ClientSession, ip: str) -> Optional[Dict[str, str]]:
    """Test if the given IP is a Controme system by checking the login page."""
    # Only check the specific login page URL
    login_url = f"http://{ip}/accounts/m_login/"
    
    try:
        # Check the login page with a short timeout
        async with async_timeout.timeout(1):
            async with session.get(login_url) as response:
                if response.status == 200:
                    # Check for the specific title in the HTML
                    text = await response.text()
                    if "<title>Smart-Heat-OS - Login</title>" in text:
                        _LOGGER.info("Found Controme system at %s", ip)
                        return {"url": ip, "title": f"Controme at {ip}"}
    except (asyncio.TimeoutError, aiohttp.ClientConnectorError, Exception):
        # Skip any errors
        pass
    
    return None

async def scan_network(networks: List[str] = None) -> List[Dict[str, str]]:
    """Scan network for Controme systems and stop after finding one."""
    start_time = asyncio.get_event_loop().time()
    
    if networks is None:
        # Get local network from Home Assistant's IP
        local_ip = get_local_ip()
        if local_ip:
            network = get_network_from_ip(local_ip)
            if network:
                _LOGGER.info("Detected local network: %s", network)
                networks = [network]
            else:
                _LOGGER.warning("Could not determine local network, using default networks")
                networks = ["192.168.1.0/24"]
        else:
            _LOGGER.warning("Could not determine local IP, using default networks")
            networks = ["192.168.1.0/24"]
    
    # Optimize connection settings for faster scanning
    connector = aiohttp.TCPConnector(limit_per_host=10, limit=100)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for network in networks:
            _LOGGER.info("Scanning network %s for Controme systems", network)
            
            try:
                # Create a single list of all IPs to scan
                all_ips = []
                
                # Prioritize some common IPs first
                priority_ips = [
                    "192.168.1.100",
                    "192.168.1.200",
                    "192.168.1.10",
                    "192.168.1.20",
                    "192.168.0.100",
                    "192.168.0.200"
                ]
                
                try:
                    ip_network = IPv4Network(network)
                    local_ip = get_local_ip()
                    
                    # Add all IPs to the list, prioritizing common ones
                    for ip in ip_network.hosts():
                        ip_str = str(ip)
                        if ip_str == local_ip:
                            continue  # Skip local IP
                        
                        if ip_str in priority_ips:
                            # Add priority IPs to the beginning
                            all_ips.insert(0, ip_str)
                        else:
                            # Add regular IPs to the end
                            all_ips.append(ip_str)
                except ValueError:
                    _LOGGER.error("Invalid network format: %s", network)
                    continue
                
                # Optimize chunk size for faster scanning
                chunk_size = 40
                
                # Process all IPs in a single pass with optimized chunks
                for i in range(0, len(all_ips), chunk_size):
                    chunk_ips = all_ips[i:i + chunk_size]
                    _LOGGER.debug("Scanning IPs %d to %d of %d", 
                                 i, min(i+chunk_size, len(all_ips)), len(all_ips))
                    
                    # Create tasks for this chunk
                    chunk_tasks = [test_controme_host(session, ip) for ip in chunk_ips]
                    
                    # Run all tasks in parallel
                    chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)
                    
                    # Process results
                    discovered_systems = []
                    for ip, result in zip(chunk_ips, chunk_results):
                        if isinstance(result, Exception):
                            continue
                        if result:
                            discovered_systems.append(result)
                            _LOGGER.info("Found Controme system: %s", result["url"])
                    
                    # If we found any systems, return immediately
                    if discovered_systems:
                        end_time = asyncio.get_event_loop().time()
                        scan_duration = end_time - start_time
                        _LOGGER.info("Network scan completed in %.2f seconds. Found %d Controme systems", 
                                   scan_duration, len(discovered_systems))
                        return discovered_systems
                
            except Exception as e:
                _LOGGER.error("Error scanning network %s: %s", network, str(e))
                continue
    
    # If we get here, no systems were found
    end_time = asyncio.get_event_loop().time()
    scan_duration = end_time - start_time
    _LOGGER.info("Network scan completed in %.2f seconds. No Controme systems found", scan_duration)
    return [] 