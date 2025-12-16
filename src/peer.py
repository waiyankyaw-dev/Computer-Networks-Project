import sys
import select
import struct
import socket
import hashlib
import argparse
import pickle
import os

# Add the parent directory (project root) to sys.path
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils import simsocket
from utils.simsocket import AddressType
from utils.peer_context import PeerContext

from typing import TypedDict, List, Dict, Tuple
import time
import math

"""
This is CS305 project skeleton code. Please refer to the example files -
  example/dump_receiver.py and
  example/dump_sender.py 
- to learn how to play with this skeleton.

The sample code is for reference only.
The given function is only one possible design, you are not required to follow it strictly.
We allow you to use better code design that conforms to best practices.
But ensure that your program's entry point is `peer.py` .
"""

BUF_SIZE: int = 1400
CHUNK_DATA_SIZE: int = 512 * 1024

HEADER_FMT: str = "BBHII"
HEADER_LEN: int = struct.calcsize(HEADER_FMT)

SHA1_HASH_SIZE = 20
MAX_PAYLOAD: int = 1024
class DownloadState(TypedDict):
    output_file: str
    chunks_to_get: List[str]
    received_chunks: Dict[str, bytes]
    peers_who_have: Dict[str, List[AddressType]]
    status: str

class ConnectionState(TypedDict):
    active_chunk_hash: str
    output_file: str
    status: str
    expected_seq_num: int 
    
    packet_buffer: Dict[int, bytes] # seq_num to data bytes 
    
    last_recv_time: float
class UploadState(TypedDict):
    chunk_hash: str
    last_ack: int
    
    cwnd: float
    ssthresh: int
    dup_ack_count: int

    estimated_rtt: float
    dev_rtt: float
    timeout_interval: float
    
    sent_time: Dict[int, float] # seq_num -> timestamp
    last_sent: int # last sent seq_num 
class Context(PeerContext):
    def __init__(self, args):
        super().__init__(args)
        
        self.active_downloads: Dict[str, DownloadState] = {} 
        self.connection_states: Dict[Tuple[str, int], ConnectionState] = {}
        self.active_uploads: Dict[Tuple[str, int], UploadState] = {}
class PktType:
    WHOHAS: int = 0
    IHAVE: int = 1
    GET: int = 2
    DATA: int = 3
    ACK: int = 4


def process_download(
    sock: simsocket.SimSocket, context: Context, chunk_file: str, output_file: str
) -> None:
    """
    Initiates and manages the download of one or more chunks.

    This function is called when a 'DOWNLOAD' command is received. It is
    responsible for reading the chunk hashes from the ``chunk_file``,
    orchestrating the network requests (e.g., sending WHOHAS, GET) to
    retrieve all necessary chunks, and saving the completed data to
    the ``output_file``.

    :param sock: The :class:`simsocket.SimSocket` for network communication.
    :param chunk_file: Path to the file containing hashes of chunks to download.
    :param output_file: Path to the file to save the downloaded chunk data.
    """
    # print("PROCESS DOWNLOAD SKELETON CODE CALLED.  Fill me in!")
    chunks_to_get: list[str] = []
    with open(chunk_file, "r") as chunk_file_handler:
        for line in chunk_file_handler:
            chunks_to_get.append(line.strip().split(" ")[1])
            
    context.active_downloads[output_file] = {
        "output_file": output_file,
        "chunks_to_get": chunks_to_get,
        "received_chunks": {}, 
        "peers_who_have": {}, # map from hash -> list of peers
        "status": "finding_peers"
    }
    
    all_hashes_list: list[bytes] = [bytes.fromhex(item) for item in chunks_to_get]
    
    all_hashes: bytes = b"".join(all_hashes_list)
    
    whohas_header: bytes = struct.pack(
        HEADER_FMT,
        PktType.WHOHAS,
        HEADER_LEN,
        socket.htons(HEADER_LEN + len(all_hashes)),
        socket.htonl(0),
        socket.htonl(0)
    )
    
    whohas_pkt: bytes = whohas_header + all_hashes
    
    peer_list: list[list[str]] = context.peers
    for p in peer_list:
        if int(p[0]) != context.identity:
            sock.sendto(whohas_pkt, (p[1], int(p[2])))
    
        

def process_inbound_udp(sock: simsocket.SimSocket, context: Context) -> None:
    """
    Processes a single inbound packet received from the socket.

    This function should receive data, unpack the standard header,
    and then use the packet type to route the packet to the appropriate
    handling logic (e.g., for WHOHAS, IHAVE, GET, DATA, ACK).

    :param sock: The :class:`simsocket.SimSocket` with a pending packet.
    :type sock: simsocket.SimSocket
    """
    # Receive pkt
    pkt: bytes
    from_addr: AddressType
    pkt, from_addr = sock.recvfrom(BUF_SIZE)

    pkg_type: int
    hlen: int
    plen: int
    seq: int
    ack: int
    pkg_type, hlen, plen, seq, ack = struct.unpack(HEADER_FMT, pkt[:HEADER_LEN])
    seq = socket.ntohl(seq)
    ack = socket.ntohl(ack)
    data: bytes = pkt[HEADER_LEN:]
    # print("SKELETON CODE CALLED, FILL this!")
    
    match pkg_type:
        case PktType.WHOHAS:
            i_have_chunkhash: list[bytes] = []
            for i in range (0, len(data), SHA1_HASH_SIZE):
                whohas_chunkhash = data[i: i+SHA1_HASH_SIZE]
                
                whohas_chunkhash_str = whohas_chunkhash.hex()
                
                if whohas_chunkhash_str in context.has_chunks:
                    i_have_chunkhash.append(whohas_chunkhash)
                    
            if i_have_chunkhash:
                # print(f"chunks i have {i_have_chunkhash}")
                whohas_chunkhash: bytes = b"".join(i_have_chunkhash)
                
                ihave_header: bytes = struct.pack(
                    HEADER_FMT,
                    PktType.IHAVE,
                    HEADER_LEN,
                    socket.htons(
                        HEADER_LEN + len(whohas_chunkhash)
                    ),  
                    socket.htonl(0),
                    socket.htonl(0),
                )
                ihave_pkt: bytes = ihave_header + whohas_chunkhash
                sock.sendto(ihave_pkt, from_addr)
                
        case PktType.IHAVE:
            ihave_hashes: list[str] = []
            for i in range (0, len(data), SHA1_HASH_SIZE):
                has_chunkhash = data[i: i+SHA1_HASH_SIZE]
                ihave_hashes.append(has_chunkhash.hex())
                
            # active_downloads is dict that maps output_file (key) to dict-like values, to access the field in value, we need to give it a key to access it
            for output_file, task_state in context.active_downloads.items():
                needed_hashes = task_state["chunks_to_get"]
                
                for ihave_hash in ihave_hashes:
                    if ihave_hash in needed_hashes:
                        
                        #init key
                        if ihave_hash not in task_state["peers_who_have"]:
                            task_state["peers_who_have"][ihave_hash] = []
                            
                        #add address
                        if from_addr not in task_state["peers_who_have"][ihave_hash]:
                            task_state["peers_who_have"][ihave_hash].append(from_addr)
            
            schedule_new_downloads(sock, context)
            
        case PktType.GET: 
            if len(data) < 20:
                return
                
            request_hash: str = data[:20].hex()
            
            if request_hash not in context.has_chunks:
                return 
            
            if len(context.active_uploads) >= context.max_conn:
                denied_header: bytes = struct.pack(
                    HEADER_FMT,
                    5,
                    HEADER_LEN,
                    socket.htons(HEADER_LEN),
                    0,
                    0,
                )
                sock.sendto(denied_header, from_addr)
                return
            
            if context.timeout > 0:
                initial_timeout = float(context.timeout)
            else:
                initial_timeout = 1
            
            context.active_uploads[from_addr] = {
                "chunk_hash": request_hash,
                "cwnd": 1.0,
                "dup_ack_count": 0.0,
                "last_ack": 0, 
                "ssthresh": 64,
                
                "estimated_rtt": initial_timeout,
                "dev_rtt": 0.0,
                "timeout_interval": initial_timeout,
                "sent_time": {},
                "last_sent": 0
                
            }
            
            send_window(sock, context, from_addr)
            
            # print("=================================================")
            # print(f"Started upload of {request_hash} to {from_addr}")
            # print("=================================================")
         
        case PktType.DATA:
            # check if the receiver is the one we expect 
            if not from_addr in context.connection_states:
                return 
            
            conn_state = context.connection_states[from_addr]
            
            # reset timer every time we talk to them 
            conn_state["last_recv_time"] = time.time() 
            
            expected_seq_num = conn_state["expected_seq_num"]
            output_file = conn_state["output_file"] 
            chunk_hash = conn_state["active_chunk_hash"]
            
            if seq == expected_seq_num:
                
                download_state = context.active_downloads[output_file]
     
     
                if chunk_hash not in download_state["received_chunks"]:
                    download_state["received_chunks"][chunk_hash] = b""
                
                download_state["received_chunks"][chunk_hash] += data
                conn_state["expected_seq_num"] += 1
                
                # check if it has already received and stored future data in buffer, take from the buffer if it does
                if "packet_buffer" in conn_state:
                    while True: 
                        next_needed = conn_state["expected_seq_num"]
                        if next_needed in conn_state["packet_buffer"]:
                            buffer_data = conn_state["packet_buffer"].pop(next_needed)
                            download_state["received_chunks"][chunk_hash] += buffer_data
                            conn_state["expected_seq_num"] += 1
                        else: 
                            break 
                        
                # accumulative ack but only the last ack one represent all 
                last_received_ack = conn_state["expected_seq_num"] - 1 
                
                ack_header = struct.pack(
                    HEADER_FMT,
                    PktType.ACK,
                    HEADER_LEN,
                    socket.htons(HEADER_LEN),
                    0,          
                    socket.htonl(last_received_ack), #ack
                )
                sock.sendto(ack_header, from_addr)
                
                if len(download_state["received_chunks"][chunk_hash]) == CHUNK_DATA_SIZE:
                                       
                    # with open(output_file, "wb") as write_file_handler:
                    #     pickle.dump(download_state["received_chunks"][chunk_hash], write_file_handler)

                    # add to has chunk
                    context.has_chunks[chunk_hash] = download_state["received_chunks"][chunk_hash]
                    

                    del context.connection_states[from_addr]
                    
                    if chunk_hash in download_state["chunks_to_get"]: 
                        download_state["chunks_to_get"].remove(chunk_hash)
                    
                    # the whole file is finished downloading
                    if len(download_state["chunks_to_get"]) == 0: 
                        # print(f"the whole download is completed: {output_file}")
                        with open(output_file, "wb") as w: 
                            pickle.dump(download_state["received_chunks"], w)
                        
                        del context.active_downloads[output_file]
                    
                    schedule_new_downloads(sock, context)
                    
            elif seq < expected_seq_num: 
                ack_header = struct.pack(
                    HEADER_FMT,
                    PktType.ACK,
                    HEADER_LEN,
                    socket.htons(HEADER_LEN),
                    0,          
                    socket.htonl(seq), #ack
                )
                sock.sendto(ack_header, from_addr)
            
            else:
                # store in buffer if seq > expected
                if "packet_buffer" not in conn_state:
                    conn_state["packet_buffer"] = {}
                conn_state["packet_buffer"][seq] = data
                
                dup_ack = conn_state["expected_seq_num"] - 1
                
                dup_ack_header = struct.pack(
                    HEADER_FMT,
                    PktType.ACK,
                    HEADER_LEN,
                    socket.htons(HEADER_LEN),
                    0,          
                    socket.htonl(dup_ack), #ack
                )
                sock.sendto(dup_ack_header, from_addr)
        
        case PktType.ACK:
                

            if from_addr not in context.active_uploads:
                return 
            
            
            upload_state = context.active_uploads[from_addr]
            request_hash: str = upload_state["chunk_hash"]
            last_ack = upload_state["last_ack"]
            
            if ack > last_ack :
                upload_state["last_ack"] = ack
                upload_state["dup_ack_count"] = 0 
                
                # time
                if context.timeout == 0 and ack in upload_state["sent_time"]:
                    sample_rtt = time.time() - upload_state["sent_time"][ack]

                    upload_state["estimated_rtt"] = 0.85 * upload_state["estimated_rtt"] + 0.15 * sample_rtt
                    upload_state["dev_rtt"] = 0.7 * upload_state["dev_rtt"] + 0.3 * abs(sample_rtt - upload_state["estimated_rtt"])
                    upload_state["timeout_interval"] = upload_state["estimated_rtt"] + 4 * upload_state["dev_rtt"]
                    
                    upload_state["timeout_interval"] = max(min(upload_state["timeout_interval"], 4.0), 0.2)
                    
                    del upload_state["sent_time"][ack]
                
                # cc
                if upload_state["cwnd"] < upload_state["ssthresh"]:
                    upload_state["cwnd"] += 1 
                else:
                    upload_state["cwnd"] += 1.0 / upload_state["cwnd"] 
                
                if upload_state["last_ack"] * MAX_PAYLOAD >= CHUNK_DATA_SIZE:
                    # print(f"Finished uploading to {from_addr}")
                    del context.active_uploads[from_addr]
                    return 
                
                send_window(sock, context, from_addr)
                
            elif ack == last_ack:
                upload_state["dup_ack_count"] += 1
                
                if upload_state["dup_ack_count"] == 3: 
                    # print("fash retransimission")
                    retransmit(sock, context, last_ack + 1, from_addr)
                    
                    upload_state["ssthresh"] = max(int(upload_state["cwnd"] / 2), 2)
                    upload_state["cwnd"] = 1

def send_window(sock: simsocket.SimSocket, context: Context, peer_addr: AddressType):
    upload_state = context.active_uploads[peer_addr]
    
    while upload_state["cwnd"] > upload_state["last_sent"] - upload_state["last_ack"]:
        next_seq = int(upload_state["last_sent"] + 1) 
        offset = (next_seq - 1) * MAX_PAYLOAD
        
        if offset >= CHUNK_DATA_SIZE:
            if upload_state["last_ack"] * MAX_PAYLOAD >= CHUNK_DATA_SIZE:
                del context.active_uploads[peer_addr]
            break 
        
        full_data = context.has_chunks[upload_state["chunk_hash"]]
        chunk_data = full_data[offset: offset + MAX_PAYLOAD]
        if len(chunk_data) == 0:
            break
        data_header: bytes = struct.pack(
            HEADER_FMT,
            PktType.DATA,
            HEADER_LEN,
            socket.htons(HEADER_LEN + len(chunk_data)),
            socket.htonl(next_seq),
            0,
        )
        sock.sendto(data_header + chunk_data, peer_addr)
        
        upload_state["last_sent"] = next_seq
        upload_state["sent_time"][next_seq] = time.time()
          
def retransmit(sock: simsocket.SimSocket, context: Context, seq: int, peer_addr: AddressType) -> None: 

    offset = (seq - 1) * MAX_PAYLOAD
    if offset >= CHUNK_DATA_SIZE: return 
    
    active_state = context.active_uploads[peer_addr]
    full_data = context.has_chunks[active_state["chunk_hash"]]
    chunk_data = full_data[offset: offset + MAX_PAYLOAD]
    
    data_header: bytes = struct.pack(
        HEADER_FMT,
        PktType.DATA,
        HEADER_LEN,
        socket.htons(HEADER_LEN + len(chunk_data)),
        socket.htonl(seq),
        0,
    )
    sock.sendto(data_header + chunk_data, peer_addr)
    
                
def schedule_new_downloads(sock: simsocket.SimSocket, context: Context) -> None:
    for output_file, task_state in context.active_downloads.items():

        needed_hashes = task_state["chunks_to_get"]
        candidates: Dict[str, List[AddressType]]  = {} # chunk -> [peers]
        
        for h in needed_hashes:
            if h in task_state["peers_who_have"]:
                candidates[h] = task_state["peers_who_have"][h]
        
        sorted_candidates = sorted(candidates.items(), key=lambda item: len(item[1]))
        
        
        for chunk, peers in sorted_candidates: 
            is_downloading = False
            
            for con in context.connection_states.values():
                if chunk == con.get("active_chunk_hash"):
                    is_downloading = True
                    break
                
            if is_downloading:
                continue
            
            for peer in peers:
                if peer not in context.connection_states:
                    
                    get_chunk_hash: bytes = bytes.fromhex(chunk)

                    # send back GET pkt
                    get_header: bytes = struct.pack(
                        HEADER_FMT,
                        PktType.GET,
                        HEADER_LEN,
                        socket.htons(HEADER_LEN + len(get_chunk_hash)),
                        socket.htonl(0),
                        socket.htonl(0),
                    )
                    get_pkt: bytes = get_header + get_chunk_hash
                    sock.sendto(get_pkt, peer)
                    
                    context.connection_states[peer] = {
                        "active_chunk_hash": chunk,
                        "output_file": output_file, 
                        "status": "downloading",
                        "expected_seq_num": 1,
                        "packet_buffer": {},
                        "last_recv_time": time.time()
                    }
                    break
            
            
def check_timeout(sock: simsocket.SimSocket, context: Context):
    now = time.time()
    for peer, upload_state in list(context.active_uploads.items()): 
        seq = upload_state["last_ack"] + 1
        
        upload_state["timeout_interval"] = max(min(upload_state["timeout_interval"], 4.0), 0.2)
        
        if seq in upload_state["sent_time"]:
            if now - upload_state["sent_time"][seq] > upload_state["timeout_interval"]:
                
                upload_state["ssthresh"] = max(int(upload_state["cwnd"] / 2), 2)
                upload_state["cwnd"] = 1      
                retransmit(sock, context, seq , peer)
                upload_state["sent_time"][seq] = now 
                
    for peer, conn_state in list(context.connection_states.items()):
        if now - conn_state["last_recv_time"] > 5.0:
            output_file = conn_state["output_file"]
            chunk_hash = conn_state["active_chunk_hash"]
            
            download_state = context.active_downloads[output_file]
            if chunk_hash in download_state["peers_who_have"]:
                if peer in download_state["peers_who_have"][chunk_hash]:
                    download_state["peers_who_have"][chunk_hash].remove(peer)
            
            if chunk_hash in download_state["received_chunks"]:
                download_state["received_chunks"][chunk_hash] = b""
            
            del context.connection_states[peer]
            
            schedule_new_downloads(sock, context) 
            
            
        
def process_user_input(sock: simsocket.SimSocket, context: Context) -> None:
    """
    Handles a single line of user input from ``sys.stdin``.

    Parses the input and, if the command is "DOWNLOAD", calls
    :func:`process_download` with the provided file paths.

    :param sock: The :class:`simsocket.SimSocket` to be passed to
                 :func:`process_download`.
    :type sock: simsocket.SimSocket
    """
    command, chunk_file, output_file = input().split()
    if command == "DOWNLOAD":
        process_download(sock,context, chunk_file, output_file)
    else:
        pass


def peer_run(context: Context) -> None:
    """
    Runs the main event loop for the peer.

    Initializes the :class:`simsocket.SimSocket` and enters a loop
    that uses :func:`select.select` to monitor both the socket for
    inbound packets (handled by :func:`process_inbound_udp`) and
    ``sys.stdin`` for user commands (handled by
    :func:`process_user_input`).

    :param context: The peer's configuration and state object.
    """
    addr: AddressType = (context.ip, context.port)
    sock = simsocket.SimSocket(context.identity, addr, verbose=context.verbose)

    try:
        while True:
            ready: tuple[list, list, list] = select.select(
                [sock, sys.stdin], [], [], 0.1
            )
            read_ready: list = ready[0]
            if len(read_ready) > 0:
                if sock in read_ready:
                    process_inbound_udp(sock, context)
                if sys.stdin in read_ready:
                    process_user_input(sock, context)
            else:
                # No pkt nor input arrives during this period
                pass
            check_timeout(sock, context)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


def main() -> None:
    """
    Main entry point for the peer script.

    Parses command-line arguments, initializes the global PeerContext,
    and starts the peer's main run loop.
    """

    """
    -i: ID, it is the index in nodes.map

    -p: Peer list file, it will be in the form "*.map" like nodes.map.

    -c: Chunkfile, a dictionary dumped by pickle. It will be loaded automatically in peer_context.
        The loaded dictionary has the form: {chunkhash: chunkdata}

    -m: The max number of peer that you can send chunk to concurrently.
        If more peers ask you for chunks, you should reply "DENIED"

    -v: verbose level for printing logs to stdout, 0 for no verbose, 1 for WARNING level, 2 for INFO, 3 for DEBUG.

    -t: pre-defined timeout. If it is not set, you should estimate timeout via RTT.
        If it is set, you should not change this time out.
        The timeout will be set when running test scripts. PLEASE do not change timeout if it set.
    """

    parser = argparse.ArgumentParser(
        description="CS305 Project Peer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--identity",
        dest="identity",
        type=int,
        help="Which peer # am I?",
    )
    parser.add_argument(
        "-p",
        "--peer-file",
        dest="peer_file",
        type=str,
        help="The list of all peers",
        default="nodes.map",
    )
    parser.add_argument(
        "-c",
        "--chunk-file",
        dest="chunk_file",
        type=str,
        help="Pickle dumped dictionary {chunkhash: chunkdata}",
    )
    parser.add_argument(
        "-m",
        "--max-conn",
        dest="max_conn",
        type=int,
        help="Max # of concurrent sending",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        type=int,
        help="verbose level",
        default=0,
    )
    parser.add_argument(
        "-t",
        "--timeout",
        dest="timeout",
        type=int,
        help="pre-defined timeout",
        default=0,
    )
    args = parser.parse_args()

    context = Context(args)
    peer_run(context)


if __name__ == "__main__":
    main()
