import os
import heapq
import pickle
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import mysql.connector

# --- GLOBAL CONSTANTS & DB CONFIGURATION ---
PLACEHOLDER = "__PLACEHOLDER__"
END_WORD = "__END_WORD__"

DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = "dharunL12" 

global_node_counter = 0

# ==============================================================================
# 1. DATABASE LOGIC (MYSQL CONNECTIVITY)
# ==============================================================================

def setup_database():
    try:
        conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, auth_plugin="mysql_native_password")
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS compressor_db")
        cursor.execute("USE compressor_db")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compression_logs (
                log_id INT AUTO_INCREMENT PRIMARY KEY,
                file_name VARCHAR(100),
                original_size INT,
                compressed_size INT,
                space_saved INT,
                compression_ratio DECIMAL(5,2)
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("MySQL Connection Error:", e)

def log_to_database(filename, orig_size, comp_size, space_saved, ratio):
    try:
        conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database="compressor_db", auth_plugin="mysql_native_password")
        cursor = conn.cursor()
        query = """INSERT INTO compression_logs 
                   (file_name, original_size, compressed_size, space_saved, compression_ratio) 
                   VALUES (%s, %s, %s, %s, %s)"""
        values = (filename, orig_size, comp_size, space_saved, ratio)
        cursor.execute(query, values)
        conn.commit()
        conn.close()
    except Exception as e:
        print("Failed to log data to MySQL:", e)

# ==============================================================================
# 2. CORE COMPRESSION LOGIC (HUFFMAN)
# ==============================================================================

def tokenize(text):
    tokens = re.findall(r'\w+|\W', text)
    return tokens

def build_frequency_dicts(tokens):
    temp_freq = {}
    for token in tokens:
        if token in temp_freq:
            temp_freq[token] += 1
        else:
            temp_freq[token] = 1

    word_freq = {PLACEHOLDER: 0}
    char_freq = {END_WORD: 1}

    for token, count in temp_freq.items():
        if not token.isalnum() or count > 2:
            word_freq[token] = count
        else:
            word_freq[PLACEHOLDER] += count
            for char in token:
                if char in char_freq:
                    char_freq[char] += count
                else:
                    char_freq[char] = count
    return word_freq, char_freq

def build_huffman_tree(freq_dict):
    global global_node_counter
    heap = []
    for key, freq in freq_dict.items():
        if freq > 0:
            global_node_counter += 1
            heapq.heappush(heap, [freq, global_node_counter, key, None, None])

    if len(heap) == 0:
        return None
    
    if len(heap) == 1:
        node = heapq.heappop(heap)
        global_node_counter += 1
        root = [node[0], global_node_counter, None, node, None]
        return root

    while len(heap) > 1:
        left_node = heapq.heappop(heap)
        right_node = heapq.heappop(heap)
        merged_freq = left_node[0] + right_node[0]
        global_node_counter += 1
        merged_node = [merged_freq, global_node_counter, None, left_node, right_node]
        heapq.heappush(heap, merged_node)
        
    return heapq.heappop(heap)

def generate_codes_helper(node, current_code, codes_dict, reverse_codes_dict):
    if node is None:
        return
    token = node[2]
    left_child = node[3]
    right_child = node[4]

    if token is not None:
        codes_dict[token] = current_code
        reverse_codes_dict[current_code] = token
        return

    generate_codes_helper(left_child, current_code + "0", codes_dict, reverse_codes_dict)
    generate_codes_helper(right_child, current_code + "1", codes_dict, reverse_codes_dict)

def generate_codes(word_freq, char_freq):
    word_root = build_huffman_tree(word_freq)
    char_root = build_huffman_tree(char_freq)

    word_codes, reverse_word_codes = {}, {}
    char_codes, reverse_char_codes = {}, {}

    generate_codes_helper(word_root, "", word_codes, reverse_word_codes)
    generate_codes_helper(char_root, "", char_codes, reverse_char_codes)

    return word_codes, reverse_word_codes, char_codes, reverse_char_codes

def pad_encoded_text(encoded_text):
    extra_padding = 8 - (len(encoded_text) % 8)
    for i in range(extra_padding):
        encoded_text += "0"
    padded_info = "{0:08b}".format(extra_padding)
    return padded_info + encoded_text

def get_byte_array(padded_encoded_text):
    b = bytearray()
    for i in range(0, len(padded_encoded_text), 8):
        byte = padded_encoded_text[i:i+8]
        b.append(int(byte, 2))
    return b

def remove_padding(padded_encoded_text):
    padded_info = padded_encoded_text[:8]
    extra_padding = int(padded_info, 2)
    padded_encoded_text = padded_encoded_text[8:]
    return padded_encoded_text[:-extra_padding]

# ==============================================================================
# 3. MAIN COMPRESS & DECOMPRESS PROCESSES
# ==============================================================================

def execute_compression(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as file:
        text = file.read()

    tokens = tokenize(text)
    word_freq, char_freq = build_frequency_dicts(tokens)
    word_codes, _, char_codes, _ = generate_codes(word_freq, char_freq)

    encoded_text = ""
    for token in tokens:
        if token in word_codes and token != PLACEHOLDER:
            encoded_text += word_codes[token]
        else:
            encoded_text += word_codes[PLACEHOLDER]
            for char in token:
                encoded_text += char_codes[char]
            encoded_text += char_codes[END_WORD]

    padded_encoded_text = pad_encoded_text(encoded_text)
    byte_array = get_byte_array(padded_encoded_text)

    metadata = {'word_freq': word_freq, 'char_freq': char_freq}
    pickled_metadata = pickle.dumps(metadata)
    meta_length = len(pickled_metadata)

    with open(output_path, 'wb') as output:
        output.write(meta_length.to_bytes(4, byteorder='big'))
        output.write(pickled_metadata)
        output.write(byte_array)

def execute_decompression(input_path, output_path):
    with open(input_path, 'rb') as file:
        meta_length = int.from_bytes(file.read(4), byteorder='big')
        pickled_metadata = file.read(meta_length)
        metadata = pickle.loads(pickled_metadata)
        
        bit_string = ""
        byte = file.read(1)
        while len(byte) > 0:
            byte = ord(byte)
            bits = bin(byte)[2:].rjust(8, '0')
            bit_string += bits
            byte = file.read(1)

    word_freq = metadata['word_freq']
    char_freq = metadata['char_freq']
    _, reverse_word_codes, _, reverse_char_codes = generate_codes(word_freq, char_freq)
    
    encoded_text = remove_padding(bit_string)

    decoded_text = []
    current_code = ""
    is_parsing_chars = False

    for bit in encoded_text:
        current_code += bit
        if not is_parsing_chars:
            if current_code in reverse_word_codes:
                token = reverse_word_codes[current_code]
                if token == PLACEHOLDER:
                    is_parsing_chars = True
                else:
                    decoded_text.append(token)
                current_code = ""
        else:
            if current_code in reverse_char_codes:
                char = reverse_char_codes[current_code]
                if char == END_WORD:
                    is_parsing_chars = False
                else:
                    decoded_text.append(char)
                current_code = ""

    with open(output_path, 'w', encoding='utf-8') as output:
        output.write("".join(decoded_text))

# ==============================================================================
# 4. GUI LOGIC (PROCEDURAL TKINTER)
# ==============================================================================

def browse_compress_file():
    path = filedialog.askopenfilename(title="Select Text File", filetypes=(("Text Files", "*.txt"), ("All Files", "*.*")))
    if path:
        compress_entry_var.set(path)

def browse_decompress_file():
    path = filedialog.askopenfilename(title="Select .vlr File", filetypes=(("VLR Compressed Files", "*.vlr"), ("All Files", "*.*")))
    if path:
        decompress_entry_var.set(path)

def display_statistics(original_size, compressed_size, process_type, filename=""):
    if process_type == "compress":
        space_saved = original_size - compressed_size
        ratio = (compressed_size / original_size) * 100 if original_size > 0 else 100.00
        stats_text = (
            f"--- Compression Statistics ---\n"
            f"Original Size: {original_size} bytes\n"
            f"Compressed Size: {compressed_size} bytes\n"
            f"Space Saved: {space_saved} bytes\n"
            f"Compression Ratio: {ratio:.2f}% of original size"
        )
        stats_label.config(text=stats_text, fg="#1B5E20")
        log_to_database(filename, original_size, compressed_size, space_saved, ratio)
    else:
        stats_text = f"--- Decompression Statistics ---\nProcess Successful!\nRestored Size: {original_size} bytes"
        stats_label.config(text=stats_text, fg="#1B5E20")

def ui_compress_action():
    input_path = compress_entry_var.get()
    if not input_path or not os.path.exists(input_path):
        messagebox.showerror("Error", "Please select a valid file.")
        return
    output_path = input_path.rsplit('.', 1)[0] + ".vlr"
    try:
        stats_label.config(text="Status: Compressing... Please wait.", fg="blue")
        root.update()
        execute_compression(input_path, output_path)
        original_size = os.path.getsize(input_path)
        compressed_size = os.path.getsize(output_path)
        filename = os.path.basename(input_path)
        display_statistics(original_size, compressed_size, "compress", filename)
        messagebox.showinfo("Success", f"File compressed successfully!\nSaved as: {os.path.basename(output_path)}")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred:\n{str(e)}")

def ui_decompress_action():
    input_path = decompress_entry_var.get()
    if not input_path or not os.path.exists(input_path):
        messagebox.showerror("Error", "Please select a valid .vlr file.")
        return
    output_path = input_path.replace(".vlr", "_decompressed.txt")
    try:
        stats_label.config(text="Status: Decompressing... Please wait.", fg="blue")
        root.update()
        execute_decompression(input_path, output_path)
        decompressed_size = os.path.getsize(output_path)
        display_statistics(decompressed_size, 0, "decompress")
        messagebox.showinfo("Success", f"File decompressed successfully!\nSaved as: {os.path.basename(output_path)}")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred:\n{str(e)}")

def open_database_logs():
    log_window = tk.Toplevel(root)
    log_window.title("MySQL Compression Logs")
    log_window.geometry("650x300")
    text_area = tk.Text(log_window, wrap="none", font=("Courier", 10))
    text_area.pack(expand=True, fill="both", padx=10, pady=10)
    try:
        conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database="compressor_db", auth_plugin="mysql_native_password")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM compression_logs ORDER BY log_id DESC")
        rows = cursor.fetchall()
        if not rows:
            text_area.insert("end", "No records found.\n")
        else:
            header = f"{'ID':<5} | {'File Name':<20} | {'Orig(B)':<10} | {'Comp(B)':<10} | {'Saved(B)':<10} | {'Ratio(%)':<8}\n"
            text_area.insert("end", header + "-"*85 + "\n")
            for row in rows:
                fname = (row[1][:17] + "...") if len(row[1]) > 20 else row[1]
                line = f"{row[0]:<5} | {fname:<20} | {row[2]:<10} | {row[3]:<10} | {row[4]:<10} | {row[5]:<8}\n"
                text_area.insert("end", line)
        conn.close()
    except Exception as e:
        text_area.insert("end", f"Database Error: {e}")
    text_area.config(state="disabled")

# ==============================================================================
# 5. GUI INITIALIZATION
# ==============================================================================

if __name__ == "__main__":
    setup_database()

    root = tk.Tk()
    root.title("Text Compressor (.vlr Format)")
    root.geometry("600x600")
    root.configure(bg="#f4f4f4")
    
    compress_entry_var = tk.StringVar()
    decompress_entry_var = tk.StringVar()

    tk.Label(root, text="Text Compressor", font=("Helvetica", 18, "bold"), bg="#f4f4f4").pack(pady=(20, 5))
    tk.Label(root, text="Word & Character Level Huffman Coding", font=("Helvetica", 10, "italic"), bg="#f4f4f4").pack(pady=(0, 20))

    comp_frame = tk.LabelFrame(root, text=" Compress File ", bg="#f4f4f4", padx=10, pady=10)
    comp_frame.pack(fill="x", padx=20, pady=5)
    tk.Entry(comp_frame, textvariable=compress_entry_var, width=50).grid(row=0, column=0, padx=5, pady=5)
    tk.Button(comp_frame, text="Browse", width=10, command=browse_compress_file).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(comp_frame, text="Compress to .vlr", width=20, bg="#4CAF50", fg="white", command=ui_compress_action).grid(row=1, column=0, columnspan=2, pady=5)

    decomp_frame = tk.LabelFrame(root, text=" Decompress .vlr File ", bg="#f4f4f4", padx=10, pady=10)
    decomp_frame.pack(fill="x", padx=20, pady=15)
    tk.Entry(decomp_frame, textvariable=decompress_entry_var, width=50).grid(row=0, column=0, padx=5, pady=5)
    tk.Button(decomp_frame, text="Browse", width=10, command=browse_decompress_file).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(decomp_frame, text="Decompress File", width=20, bg="#2196F3", fg="white", command=ui_decompress_action).grid(row=1, column=0, columnspan=2, pady=5)

    stats_frame = tk.Frame(root, bg="#f4f4f4")
    stats_frame.pack(fill="both", expand=True, padx=20, pady=5)
    
    stats_label = tk.Label(stats_frame, text="Status: Waiting for input...", font=("Courier", 11), bg="#f4f4f4")
    stats_label.pack(pady=10)

    tk.Button(stats_frame, text="View Database Logs", width=25, bg="#FF9800", fg="white", command=open_database_logs).pack(side="bottom", pady=10)

    root.mainloop()
