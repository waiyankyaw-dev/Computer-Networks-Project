# Reliable P2P File Transfer over UDP

> **Course:** Computer Networks (Fall 2025)  
> **Language:** Python 3.10+  
> **Key Concepts:** UDP, Reliable Data Transfer (RDT), Congestion Control (TCP Reno), Socket Programming, Multiplexing

## 📖 Overview
This project implements a **Peer-to-Peer (P2P) file transfer application** that operates over an unreliable channel (UDP). While standard UDP offers no guarantees of delivery or ordering, this application implements a custom application-layer protocol to ensure **Reliable Data Transfer (RDT)**.

The system mimics features of TCP and BitTorrent, including a "WhoHas/IHave" handshake mechanism for peer discovery, sliding window flow control, and a full congestion control state machine (Slow Start, Congestion Avoidance, Fast Retransmit).

## 🚀 Key Features

### 1. Reliable Data Transfer (RDT)
Unlike standard UDP, this application ensures file integrity through:
* **Packet Sequencing:** Handles out-of-order packets using sequence numbers.
* **Acknowledgements (ACKs):** Implements cumulative ACKs to confirm data receipt.
* **Timeout & Retransmission:** Estimates Round Trip Time (RTT) dynamically using Exponential Weighted Moving Average (EWMA) to trigger retransmissions on packet loss.

### 2. Congestion Control (TCP Reno Style)
Implemented a complete finite state machine to handle network congestion:
* **Slow Start:** Exponential window growth ($cwnd \times 2$) upon connection initialization.
* **Congestion Avoidance:** Linear window growth ($cwnd + 1/cwnd$) after reaching the `ssthresh`.
* **Fast Retransmit:** Detects packet loss via 3 duplicate ACKs and retransmits immediately without waiting for a timeout.
* **Window Management:** Dynamic adjustment of the Congestion Window (`cwnd`) based on network conditions.

### 3. P2P Architecture
* **Handshaking:** Uses a flooding protocol (`WHOHAS` broadcast) to locate peers possessing specific file chunks.
* **Concurrent Transfer:** Utilizes `select()` (I/O multiplexing) to handle multiple incoming and outgoing connections simultaneously on a single thread.
* **Chunking:** Files are split into 512KiB chunks, hashed (SHA-1) for verification, and assembled upon download.

## 🛠️ Protocol Specification

The application uses a custom binary packet structure defined using Python's `struct` module:

| Field | Size | Description |
|:--- |:---:|:--- |
| **Type** | 1 byte | Packet type (WHOHAS, IHAVE, GET, DATA, ACK, DENIED) |
| **Header Len** | 1 byte | Length of the header |
| **Pkt Len** | 2 bytes | Total packet length |
| **Seq Num** | 4 bytes | Sequence number (per packet) |
| **Ack Num** | 4 bytes | Acknowledgment number |
| **Payload** | Variable | Data or Hash list |

**Packet Types:**
* `0`: **WHOHAS** (Broadcast query for file chunks)
* `1`: **IHAVE** (Response confirming ownership)
* `2`: **GET** (Requesting a specific chunk)
* `3`: **DATA** (File content payload)
* `4`: **ACK** (Acknowledgment)
* `5`: **DENIED** (Connection limit reached)

## 💻 Installation & Usage

### Prerequisites
* Python 3.10 or higher
* Linux environment (or WSL on Windows)
* Perl (for the `hupsim.pl` network simulator)

### Running the Simulator
The project runs on top of a network simulator (`hupsim.pl`) to artificially introduce delay and packet loss.

```bash
# Terminal 1: Start the simulator
perl utils/hupsim.pl -m utils/topo.map -n utils/nodes.map -p 12345 -v 1

# Terminal 2: Start a peer (Sender/Receiver)
export SIMULATOR="127.0.0.1:12345"

# Example: Run Peer with ID 1
python3 -m src.peer -p utils/nodes.map -c utils/data1.fragment -m 4 -i 1 -v 3
```

### Downloading a File
Once the peer is running, you can issue commands via stdin:

```
DOWNLOAD [chunkhash_file_path] [output_filename]
```

## 📂 Project Structure

```
.
├── src/
│   ├── peer.py           # Main entry point: Handles sockets, state machine, and logic
├── utils/
│   ├── simsocket.py      # Socket wrapper for the simulator
│   ├── hupsim.pl         # Network topology simulator (Perl)
│   ├── make_data.py      # Script to split files into chunks
├── example/              # Demo sender/receiver scripts
└── tests/                # Test scripts
```

## 🧠 Implementation Details

### State Management
The `peer.py` utilizes typed dictionaries (`ConnectionState`, `UploadState`, `DownloadState`) to track the complex state of every concurrent connection. This ensures that a single thread can manage reliable uploads to Peer A while simultaneously downloading missing chunks from Peer B.

### RTT Estimation
To ensure the timeout interval is appropriate for current network conditions, the code calculates:

$$
\begin{aligned}
&EstimatedRTT = (1 - \alpha) \cdot EstimatedRTT + \alpha \cdot SampleRTT \\
&DevRTT = (1 - \beta) \cdot DevRTT + \beta \cdot |SampleRTT - EstimatedRTT| \\
&TimeoutInterval = EstimatedRTT + 4 \cdot DevRTT
\end{aligned}
$$

(Where $\alpha = 0.125$ and $\beta = 0.25$)

---
# Local DNS Server Implementation

A multi-threaded, iterative Local DNS Server implemented in Python. This project was developed as part of the CS305 Computer Networks Lab Assignment.

The server acts as an intermediary between a client (like `dig` or a web browser) and the public DNS infrastructure. Instead of relying on a recursive upstream resolver (like 8.8.8.8) for the full resolution, this server performs **iterative queries** starting from the Root Servers down to the Authoritative Name Servers to resolve domain names.

## 🚀 Features

### 1. Iterative DNS Resolution
- **Full Traversal:** Performs iterative queries starting from Root DNS servers, moving to Top-Level Domain (TLD) servers, and finally Authoritative servers.
- **Robust Root Discovery:** Dynamically discovers the fastest/available Root Server IP upon startup using a bootstrap list, falling back to hardcoded roots if necessary.
- **CNAME Handling:** Correctly follows CNAME chains to resolve the final A record.

### 2. High Performance Caching
- **Disk Persistence:** Caches DNS records to a local file (`dns_cache.pkl`) using `pickle`, ensuring cache survival across server restarts.
- **LRU Eviction:** Implements Least Recently Used (LRU) policy using `OrderedDict` to manage cache size (Max 200 entries).
- **TTL Management:** Respects Time-To-Live (TTL) values.
    - Standard successful queries: 300s
    - NXDOMAIN (Negative caching): 60s
- **Thread Safety:** Uses `threading.Lock` to prevent race conditions during cache reads/writes.

### 3. Concurrency
- **Producer-Consumer Model:** Decouples packet reception and processing using thread-safe queues (`request_queue`, `response_queue`).
- **Multi-threaded Architecture:** 
    - Receiver Thread
    - Sender Thread
    - Pool of 30 Worker Threads (`DNSHandler`) to process queries in parallel.
- **Non-blocking I/O:** capable of handling concurrent requests efficiently (verified < 0.3s response time for cached concurrent batches).

### 4. Traffic Control (Firewall Features)
- **DNS Redirection:** Redirects specific domains to custom IPs (e.g., redirecting `google.com` to `127.0.0.1` or blocking ads by redirecting to `0.0.0.0`).
- **DNS Filtering/Blocking:** Blocks malicious or distracting domains (e.g., `malware-site.com`) by returning `REFUSED` (RCODE 5) or a custom TXT record explaining the block.

## 🛠️ Architecture

The project is structured into four main classes:

1.  **`DNSServer`**: The main entry point. Sets up the UDP socket (Port 5533), manages the thread pool, and handles the graceful start/stop lifecycle.
2.  **`DNSHandler`**: The worker logic. Parses incoming packets, checks the Blocklist/Redirect map, queries the Cache, or initiates the Iterative Query process.
3.  **`CacheManager`**: Manages storage, retrieval, locking, expiration, and auto-saving of DNS records.
4.  **`ReplyGenerator`**: Helper class to construct standard DNS response packets using `dnslib`.

## 📋 Prerequisites

- **Python 3.12+**
- **Libraries:**
  ```bash
  pip install dnslib dnspython
  ```

## 🏃 Usage

1.  **Start the Server:**
    Run the main script. The server will listen on `0.0.0.0:5533`.
    ```bash
    python LocalDNSServer.py
    ```

2.  **Test with `dig`:**
    Open a separate terminal and query your local server.
    ```bash
    # Standard Query
    dig @127.0.0.1 -p 5533 www.baidu.com

    # Query a domain that triggers the Blocker (Example)
    dig @127.0.0.1 -p 5533 malware-site.com
    ```

3.  **Stop the Server:**
    Press `Ctrl+C` in the server terminal. The server will save the current cache to disk before shutting down.

## ⚙️ Configuration

You can modify the `DNSHandler` class in `LocalDNSServer.py` to customize the redirection and blocking rules:

**Redirection Map:**
```python
self.redirect_map = {
    "www.google.com": "127.0.0.1",
    "doubleclick.net": "0.0.0.0",
    # Add custom rules here
}
```

**Blocklist:**
```python
self.blocklist = {
    "malware-site.com",
    "phishing-attack.net",
    # Add domains to block here
}
```

## 🧪 Testing Results

The server has been tested against:
- **Functional Tests:** Successfully resolves A records, follows CNAMEs, and handles NXDOMAIN.
- **Concurrency Tests:** Handled batches of 25 simultaneous queries with significant speedup on subsequent runs due to caching.
- **Wireshark Analysis:** Packet captures confirm the server performs genuine iterative queries (RD=0) rather than recursive forwarding.

## 📝 License

This project is for educational purposes (CS305 Project and Lab Assignment).

