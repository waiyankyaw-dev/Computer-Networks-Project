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

## ⚠️ Academic Integrity Disclaimer

This repository contains my solution for the CS305 Course Project. If you are currently taking this course, please do not copy this code. It is published here for portfolio and educational purposes only. Plagiarism is a serious violation of academic integrity policies.
