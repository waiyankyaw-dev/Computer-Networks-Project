import threading
import socket
import time
import pickle
from collections import OrderedDict
from queue import Queue, Empty
from dnslib import DNSRecord, QTYPE, RR, A, CNAME, DNSHeader, TXT
from dns import resolver, rdatatype, name as dns_name

class CacheManager:
    """
    --- Task 2. Automatic Cache Saving and Loading ---
    This class is responsible for managing all cache operations in the DNS server. It not only implements efficient in-memory caching,
    but also supports persisting the cache to a disk file, enabling state recovery after server restarts.
    Core features include:
    - Thread-safe design, ensuring data consistency under high-concurrency environments.
    - Automatic expiration based on TTL (Time to Live).
    - LRU (Least Recently Used) eviction policy, automatically removing the least recently accessed entries when the cache is full.
    - Automatically loading the cache file on server startup and saving it on shutdown.
    """
    def __init__(self, cache_file='dns_cache.pkl', max_size=200, auto_save_count=30): # autosave every 30 writes
        """
        Initialize a CacheManager instance.
        This constructor sets the path and maximum capacity of the cache file,
        and immediately attempts to call _load_from_file to load existing cache from disk.
        """
        self.cache_file = cache_file #file path where cache will be saved
        self.max_size = max_size  #maximum number of cache entries before LRU eviction
        self.lock = threading.Lock() #thread lock to ensure thread-safe operations
        self.write_count = 0 #counter for auto save
        self.auto_save_count = auto_save_count #save every N writes
        self.cache = self._load_from_file() #load existing cache from disk or create empty
    
    def _load_from_file(self):
        """
        --- Task 2.1 Load Cache from File ---
        At server startup, load and initialize the cache from a disk file.
        This method attempts to open the specified cache file and deserialize its data using pickle.
        Upon successful loading, it iterates through all cache entries and precisely removes any records
        that have expired during the server's downtime, based on their stored expiration timestamps,
        ensuring only valid cache entries are loaded into memory.
        :return:
            - collections.OrderedDict: If loading succeeds, returns an ordered dictionary containing valid cache entries.
            - collections.OrderedDict: If the file does not exist, is empty, or corrupted, returns a new empty ordered dictionary.
        """
        try:
            # open cache file in binary read mode
            with open(self.cache_file, 'rb') as f:
                data = pickle.load(f) #deserialize the cache data using pickle
                now = time.time() #get current timestamp for expiration check
                valid_cache = OrderedDict()#create new ordered dict for valid entries
                
                # iterate through all cached items and filter out expired ones
                for key, (record, expiry) in data.items():
                    if expiry > now:  #only keep entries that haven't expired
                        valid_cache[key] = (record, expiry)
                print(f"Loaded {len(valid_cache)} valid cache entries from {self.cache_file}")
                return valid_cache
        except (FileNotFoundError, EOFError, pickle.UnpicklingError):
            # return empty cache if file doesn't exist or is corrupted
            print(f" No existing cache file found or cache is empty. Starting with fresh cache.")
            return OrderedDict()
    
    def save_to_file(self):
        """
        --- Task 2.2 Save Cache to File ---
        Persist all current in-memory cache entries to a disk file.
        This method is typically called when the server shuts down normally. It locks the cache,
        then uses pickle to serialize the entire in-memory self.cache ordered dictionary
        and writes it completely to the designated cache file.
        :return:
            - None: This function does not return a value.
        """
        with self.lock: #acquire lock to prevent concurrent modifications during save
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.cache, f) #serialize and write entire cache to file
            print(f"Cache saved to {self.cache_file} ({len(self.cache)} entries)")
    
    def readCache(self, domain_name, qtype_str):
        """
        --- Task 2.3 Read Cache & Task 2.5 TTL (partial implementation) ---
        Retrieve a DNS record from the in-memory cache based on domain name and query type.
        This method is the core logic for reading from the cache. It first checks whether the requested record exists.
        If it does, it performs a critical TTL check: comparing the current time with the stored expiration timestamp.
        If the record has not expired, it returns the record; otherwise, it deletes the entry from the cache and returns None,
        triggering a new network query.
        :param domain_name: (str) The domain name being queried.
        :param qtype_str: (str) The record type being queried (e.g., "A", "CNAME").
        :return:
            - dnslib.DNSRecord: If a valid, unexpired cached record is found, return the record object.
            - None: If no such record exists in the cache or the record has expired, return None.
        """
        key = (domain_name.lower(), qtype_str) #create cache key from lowercase domain and query type
        with self.lock: #thread-safe access to cache
            if key in self.cache:
                record, expiry = self.cache[key] #unpack the cached record and its expiration time
                now = time.time()
                if expiry > now: #check if record is still valid
                    self.cache.move_to_end(key) #move to end to mark as recently used (LRU)
                    return record
                else:
                    del self.cache[key] #remove expired entry from cache
        return None #return None if no valid cache entry found
    
    def writeCache(self, domain_name, qtype_str, response_record):
        """
        --- Task 2.4 Write Cache & Task 2.5 TTL (partial implementation) ---
        Write a new DNS query result into the in-memory cache.
        This method is the core logic for writing to the cache. It first calculates the TTL from the DNS response
        and combines it with the current time to generate an absolute future "expiration timestamp". Then,
        it stores the DNS response record along with this timestamp as a unit in the cache. This method also handles
        negative caching (setting a fixed TTL for NXDOMAIN) and enforces the LRU eviction policy.
        :param domain_name: (str) The domain name that was queried.
        :param qtype_str: (str) The type of the queried record.
        :param response_record: (dnslib.DNSRecord) The complete DNS response object containing the data to be cached.
        :return:
            - None: This function does not return a value.
        """
        key = (domain_name.lower(), qtype_str) #create cache key
        now = time.time()
        
        # determine TTL based on response type
        if response_record.header.rcode == 3: #NXDOMAIN
            ttl = 60 #shorter TTL for negative caching
        else:
            ttl = 300 #standard 5-minute TTL for successful responses
            
        expiry = now + ttl #calculate absolute expiration timestamp
        
        with self.lock: #thread-safe cache modification
            self.cache[key] = (response_record, expiry) #store record with expiration
            self.cache.move_to_end(key) #mark as recently used
            
            # auto save logic - save every N writes
            self.write_count += 1
            if self.write_count >= self.auto_save_count:
                self.save_to_file()
                self.write_count = 0 #reset counter
            
            # enforce LRU eviction if cache exceeds maximum size
            if len(self.cache) > self.max_size:
                removed_key = self.cache.popitem(last=False)  #remove least recently used item
                print(f"Cache full, evicted: {removed_key[0]}")
    
    def force_save(self):
        """Force immediate cache save"""
        self.save_to_file()

class ReplyGenerator:
    """This class is used to generate various DNS response packets."""
    @staticmethod
    def replyForNotFound(income_record):
        """Generate NXDOMAIN response for non-existent domains"""
        header = DNSHeader(id=income_record.header.id, qr=1, rcode=3) #qr=1 (response), rcode=3 (NXDOMAIN)
        record = DNSRecord(header, q=income_record.q) #include original question
        return record
    
    @staticmethod
    def myReply(income_record, rr_list):
        """Generate successful response with resource records"""
        header = DNSHeader(id=income_record.header.id, qr=1, aa=0, ra=0)
        response = DNSRecord(header, q=income_record.q)
        for rr in rr_list:
            response.add_answer(rr)
        return response
    
    @staticmethod
    def replyForRedirect(income_record, redirect_ip, ttl=300):
        """
        --- Task 3.2 DNS Redirection (Response Construction) ---
        Construct a custom DNS response packet for DNS redirection functionality.
        When the server decides to redirect a domain name request to another IP address,
        this method generates a DNS response containing a "forged" A record. This response tells the client
        that the IP address corresponding to the queried domain is our specified redirect_ip.
        :param income_record: (dnslib.DNSRecord) The original DNS query request sent by the client.
                              We use it to retrieve the request ID and question section to ensure
                              the response can be correctly recognized by the client.
        :param redirect_ip: (str) The target IPv4 address to which the original domain should be redirected.
        :param ttl: (int, optional) The Time-To-Live for this forged A record, in seconds. Defaults to 300.
        :return:
            - dnslib.DNSRecord: A fully constructed DNS response object whose answer section
                                contains an A record pointing to redirect_ip.
        """
        header = DNSHeader(id=income_record.header.id, qr=1, aa=0, ra=0)
        response = DNSRecord(header, q=income_record.q)
        #A record resource record pointing to redirect IP
        rr = RR(income_record.q.qname, QTYPE.A, rdata=A(redirect_ip), ttl=ttl)
        response.add_answer(rr)  #add the forged A record to answer section
        return response
    
    @staticmethod
    def replyForBlocked(income_record, reason="Blocked due to security policy"):
        """
        --- Task 3.3 DNS Filtering (Response Construction) ---
        Construct a custom DNS response packet to explicitly refuse a query for a blocked domain.
        Instead of simply pretending the domain does not exist (NXDOMAIN), this method
        generates a response with a "Refused" status code (RCODE 5). This accurately
        informs the client that the query was intentionally denied due to a policy,
        which is a more precise and informative way to handle filtering.
        Optionally, it can include a TXT record to provide a human-readable reason for the block.
        :param income_record: (dnslib.DNSRecord) The original DNS query request sent by the client.
                              This is used to match the transaction ID and question section.
        :param reason: (str, optional) The reason for the block, which will be embedded in a
                                     TXT record in the answer section. If None, no TXT record is added.
        :return:
            - dnslib.DNSRecord: A DNS response object with a 'Refused' status code.
        """
        #response header with rcode=5 (Refused)
        header = DNSHeader(id=income_record.header.id, qr=1, rcode=5)
        response = DNSRecord(header, q=income_record.q)
        if reason:
            #TXT record containing the block reason
            txt_rr = RR(income_record.q.qname, QTYPE.TXT, rdata=TXT(reason), ttl=0)
            response.add_answer(txt_rr) #add TXT record to answer section
        return response

class DNSServer:
    """
    --- Task 1.2 DNSServer Implementation ---
    This class serves as the central coordinator of the entire DNS server, acting like an "air traffic controller".
    It does not perform the complex logic of DNS resolution itself, but instead manages the server's lifecycle,
    including startup, receiving client requests, dispatching tasks to worker threads (DNSHandler),
    collecting results, and sending final responses back to clients.
    To achieve high performance and concurrency, this class employs the classic multi-threaded "producer-consumer" model.
    """
    def __init__(self, source_ip, source_port, ip='0.0.0.0', port=5533, num_workers=30):
        """
        Initialize a DNSServer instance.
        This method sets up basic server configurations such as listening IP and port,
        creates the main socket required for network communication, and prepares the infrastructure for multi-threading.
        """
        self.source_ip = source_ip #ip for outgoing DNS queries
        self.source_port = source_port #Port for outgoing DNS queries
        self.ip = ip  # ip to listen on for incoming DNS queries
        self.port = port # port to listen on for incoming DNS queries(5533)
        
        # create UDP socket and bind to listening address
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.ip, self.port))
        
        # create queues for producer-consumer pattern
        self.request_queue = Queue()  #queue for incoming requests
        self.response_queue = Queue()  #queue for outgoing responses
        
        # initialize cache manager with auto-save for every 30 writes
        self.cache_manager = CacheManager(auto_save_count=30)
        
        # create worker threads
        self.workers = []
        self.running = threading.Event()  #event flag to control server lifecycle
        self.running.set()  #set the flag to indicate server should run
        
        #create and start worker threads
        for i in range(num_workers):
            worker = DNSHandler(self.source_ip, self.source_port, self.cache_manager,
                              self.request_queue, self.response_queue, i)
            worker.daemon = True  #daemon threads will exit when main thread exits
            self.workers.append(worker)
            
        # create receiver thread(producer)
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.receive_thread.daemon = True
        
        # create sender thread(consumer)
        self.send_thread = threading.Thread(target=self._send_loop)
        self.send_thread.daemon = True
    
    def start(self):
        """
        Start the full service of the DNS server.
        This method brings the server into active state, including binding the port, starting all background threads
        (receiver, sender, worker pool), and keeping the main thread waiting for shutdown signals.
        """
        # start all worker threads
        for worker in self.workers:
            worker.start()
            
        # start receiver and sender threads
        self.receive_thread.start()
        self.send_thread.start()
        
        print(f"Server started on {self.ip}:{self.port}")
        print(f"Outbound communication IP: {self.source_ip}")
        print(f"Cache auto-save enabled (every 10 writes)")
        print("⏹Press Ctrl+C to stop server and save cache")
        
        # main thread loop<keeps server running until stopped>
        while self.running.is_set():
            time.sleep(1)
    
    def stop(self):
        """
        --- Task 1.2 stop method ---
        Gracefully shut down the server and perform necessary cleanup.
        """
        print("Stopping server...")
        self.running.clear() #clear running flag to stop all threads
        self.cache_manager.force_save() #force final cache save
        self.socket.close()  #close the server socket
        print("Server stopped successfully")
    
    def _receive_loop(self):
        """
        --- Task 1.2 Receive Messages ---
        This method runs in a separate "receiver" thread, solely responsible for listening on the network port.
        """
        while self.running.is_set():
            try:
                # wait for incoming DNS queries (blocking call)
                data, addr = self.socket.recvfrom(2048)
                # put received data and client address into request queue
                self.request_queue.put((data, addr))
            except OSError:
                break #break if socket is closed
            except Exception:
                pass #ignore other exceptions and continue
    
    def _send_loop(self):
        """
        --- Task 1.2 Send Messages ---
        This method runs in a separate "sender" thread, solely responsible for sending responses.
        """
        while self.running.is_set():
            try:
                #get response data and client address from response queue
                addr, data = self.response_queue.get(timeout=1)
                #send DNS response back to client
                self.socket.sendto(data, addr)
            except Empty:
                continue #no responses in queue
            except OSError:
                break # break if socket is closed
            except Exception:
                pass # ignore other exceptions and continue

class DNSHandler(threading.Thread):
    """Worker thread class that handles actual DNS query processing"""
    
    def __init__(self, source_ip, source_port, cache_manager, request_queue, response_queue, worker_id):
        super().__init__()
        self.source_ip = source_ip      # Your IP address for outbound communication
        self.source_port = source_port  # Port for outgoing queries
        
        # list of public DNS servers for bootstrap and fallback
        self.BOOTSTRAP_DNS_SERVERS = ['223.5.5.5', '119.29.29.29', '180.76.76.76', '8.8.8.8', '1.1.1.1']
        
        # shared resources
        self.cache_manager = cache_manager
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.worker_id = worker_id
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.udp_sock.bind((self.source_ip, 0))
        except Exception:
            pass
        self.udp_sock.settimeout(1.0)
        
        # initialize root server IP cache
        self.root_server_cache = self._initialize_root_server()
        # DNS Redirection Rules (redirect_map)
        self.redirect_map = {
            "www.google.com": "127.0.0.1",
            "google.com": "127.0.0.1",
            "doubleclick.net": "0.0.0.0",
            "www.google-analytics.com": "0.0.0.0",
            "friendly.name": "8.8.8.8"
        }
        # DNS Filtering Rules (blocklist)
        self.blocklist = {
            "malware-site.com",
            "phishing-attack.net",
            "ads.annoying-tracker.com",
            "stats.unwanted-data-miner.org",
            "distracting-social-media.com"
        }
    
    def _initialize_root_server(self):
        """Initialize root server IP for this worker thread"""
        try:
            # query public DNS to get current root server IP
            server_ip, _ = self.queryRoot(self.source_ip, self.source_port)
            print(f"Worker {self.worker_id} initialized with root IP: {server_ip}")
            return server_ip
        except Exception as e:
            # fallback to hardcoded root server if bootstrap fails
            print(f"Worker {self.worker_id} failed to init root server: {e}. Falling back to 198.41.0.4.")
            return '198.41.0.4'  # a.root-servers.net
    
    def run(self):
        """Main loop for worker thread - processes requests from queue"""
        while True:
            try:
                # get next request from queue (waits up to 1 second)
                message, address = self.request_queue.get(timeout=1)
                # process the DNS query and generate response
                response_record = self.handle(message)
                if response_record:
                    # put response back into response queue for sending
                    self.response_queue.put((address, response_record.pack()))
            except Empty:
                continue  # no requests in queue, continue waiting
            except Exception:
                pass     # ignore processing errors and continue
    
    def handle(self, message):
        """Handle a single DNS query, incorporating filtering and redirection logic."""
        try:
            # parse incoming DNS message
            income_record = DNSRecord.parse(message)
            # extract domain name and query type from question section
            domain_name = str(income_record.q.qname).rstrip('.')
            qtype_str = QTYPE[income_record.q.qtype]
            #check if domain should be redirected
            if domain_name.lower() in self.redirect_map:
                redirect_ip = self.redirect_map[domain_name.lower()]
                # generate redirect response with forged IP
                return ReplyGenerator.replyForRedirect(income_record, redirect_ip)
            #check if domain should be blocked
            if domain_name.lower() in self.blocklist:
                # generate blocked response
                return ReplyGenerator.replyForBlocked(income_record)
            
            #check cache first
            cached = self.cache_manager.readCache(domain_name, qtype_str)
            if cached:
                cached.header.id = income_record.header.id #match transaction ID
                return cached  # return cached response
            # cache miss - perform iterative DNS query
            rr_list = self.query(domain_name, income_record.q.qtype)
            if rr_list:
                # generate successful response with resource records
                response = ReplyGenerator.myReply(income_record, rr_list)
                # cache the successful response
                self.cache_manager.writeCache(domain_name, qtype_str, response)
                return response
            else:
                # generate NXDOMAIN response for non existent domains
                response_record = ReplyGenerator.replyForNotFound(income_record)
                # cache the negative response
                self.cache_manager.writeCache(domain_name, qtype_str, response_record)
                return response_record
        except Exception as e:
            print(f"Error handling query: {e}")
            # return NXDOMAIN for any processing errors
            return ReplyGenerator.replyForNotFound(DNSRecord.parse(message))
        
    def resolve_nameserver(self, ns_name):
        ns_rrs = self.query(ns_name, QTYPE.A)
        if ns_rrs:
            for rr in ns_rrs:
                if rr.rtype == QTYPE.A:
                    return str(rr.rdata)
        return None
    
    def query(self, query_name, qtype):
        current_server = self.root_server_cache
        max_hops = 20
        hop_count = 0
        all_answers = [] #collect all answers including CNAMEs and final A records
        
        while hop_count < max_hops:
            hop_count += 1
            
            # reate DNS query with RD=0 for iterative queries
            q = DNSRecord.question(query_name, QTYPE.get(qtype, 'A'))
            q.header.rd = 0
            q.header.ra = 0
            
            try:
                query_data = q.pack()
                self.udp_sock.sendto(query_data, (current_server, 53)) #send query
                data, _ = self.udp_sock.recvfrom(4096) #receive response
                response = DNSRecord.parse(data) #parse response
                
                # process all resource records in answer section
                if response.rr:
                    cname_found = False
                    
                    for rr in response.rr:
                        # add all answers to our collection
                        all_answers.append(rr)
                        
                        # if we find a CNAME, we need to follow it
                        if rr.rtype == QTYPE.CNAME:
                            cname_found = True
                            # update query_name to follow CNAME chain
                            query_name = str(rr.rdata).rstrip('.')
                            # reset server to root and continue
                            current_server = self.root_server_cache
                            hop_count = 0 #reset hop count for new query
                            break  # break to process the CNAME
                    
                    # if we found a CNAME, continue with the new query
                    if cname_found:
                        continue
                    
                    # if we have direct answers(not CNAME), return all collected answers
                    if all_answers:
                        return all_answers
                
                # if no direct answers, look for referrals in authority section
                if response.auth:
                    #find NS records in authority section
                    ns_records = []
                    for auth in response.auth:
                        if auth.rtype == QTYPE.NS:
                            ns_records.append(str(auth.rdata).rstrip('.'))
                    
                    # look for A records of nameservers in additional section
                    if ns_records and response.ar:
                        for ar in response.ar:
                            if ar.rtype == QTYPE.A and str(ar.rname).rstrip('.') in ns_records:
                                current_server = str(ar.rdata)
                                break
                        continue
                    
                    # if we have NS records but no glue records, we need to resolve NS first
                    elif ns_records:
                        ns_ip = self.resolve_nameserver(ns_records[0])
                        if ns_ip:
                            current_server = ns_ip
                            continue
                
                # if we get here and have answers, return them
                if all_answers:
                    return all_answers
                return None
                
            except socket.timeout:
                if current_server in self.BOOTSTRAP_DNS_SERVERS:
                    next_index = (self.BOOTSTRAP_DNS_SERVERS.index(current_server) + 1) % len(self.BOOTSTRAP_DNS_SERVERS)
                    current_server = self.BOOTSTRAP_DNS_SERVERS[next_index]
                    continue
                return all_answers if all_answers else None
            except Exception as e:
                print(f"Query error for {query_name}: {e}")
                return all_answers if all_answers else None
        
        return all_answers if all_answers else None
    
    def queryRoot(self, source_ip, source_port):
        """
        --- Task 1.4 Robust Dynamic Discovery of Root Server IP ---
        Dynamically and reliably discover the IP address of a currently available root DNS server.
        The iterative DNS query of a local DNS server must start from a root server. However, root server IPs may change
        or become inaccessible due to DNS pollution. This method queries a preset list of reliable public DNS servers
        to dynamically obtain a valid root server IP, serving as the "starting point" for all subsequent queries.
        :param source_ip: (str) Source IP address to use for this bootstrap query.
        :param source_port: (int) Source port to use for this bootstrap query.
        :return:
            - tuple: On success, returns (root_ip, root_ns_name), where:
                - root_ip (str): IPv4 address of a root server.
                - root_ns_name (str): Domain name of that root server.
        :raises Exception: If none of the preset public DNS servers can return a root server IP.
        """
        # try each bootstrap DNS server until one works
        for bootstrap in self.BOOTSTRAP_DNS_SERVERS:
            try:
                res = resolver.Resolver()
                res.nameservers = [bootstrap]  # set resolver to use this bootstrap server
                
                # query for root nameservers (NS records for root ".")
                ans = res.resolve('.', rdatatype.NS)
                root_ns = str(ans[0]).rstrip('.')  # get first root nameserver
                
                # resolve the root nameserver to get its IP address
                ans_a = res.resolve(root_ns, rdatatype.A)
                root_ip = str(ans_a[0])  # get IP address
                
                return root_ip, root_ns
            except Exception:
                pass  # try next bootstrap server if this one fails
                
        # if all bootstrap servers fail, raise exception
        raise Exception("Failed to discover root server IP from all bootstrap servers.")

def get_local_ip():
    """
    --- Task 1.1 Automatically Detect Outbound Interface IP ---
    When performing network communication, especially on machines with multiple interfaces (Ethernet, Wi-Fi, VPN),
    the program needs to know which IP to use as the source so that response packets are correctly routed back.
    This function aims to automatically discover this "best" outbound IP address.
    :return:
        - str: On success, returns the local IP address as a string (e.g., '192.168.1.100').
        - str: On failure (e.g., no network, firewall), returns a robust fallback '0.0.0.0'.
    """
    try:
        # connect to a public DNS server for outbound interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 53)) #Google DNS
        ip = s.getsockname()[0]  #get the local IP that would be used
        s.close()
        return ip
    except Exception:
        return '0.0.0.0' # fallback address

if __name__ == '__main__':
    source_ip = get_local_ip()
    print(f"Automatically detected local IP address for outbound communication: {source_ip}")
    
    local_dns_server = DNSServer(
        source_ip=source_ip,
        source_port=0,
        ip='0.0.0.0',
        port=5533,
        num_workers=30
    )
    
    try:
        local_dns_server.start()
    except KeyboardInterrupt:
        print("\nReceived Ctrl+C - Shutting down gracefully...")
        local_dns_server.stop()
    except Exception as e:
        print(f"\nServer error: {e}")
        local_dns_server.stop()