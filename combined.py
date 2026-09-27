import hashlib
import struct

from pypdf import PdfReader
from Crypto.Cipher import ARC4

PASSWORD_PADDING = (
    b"\x28\xbf\x4e\x5e\x4e\x75\x8a\x41"
    b"\x64\x00\x4e\x56\xff\xfa\x01\x08"
    b"\x2e\x2e\x00\xb6\xd0\x68\x3e\x80"
    b"\x2f\x0c\xa9\xfe\x64\x53\x69\x7a"
)


def pad_password(password: bytes) -> bytes:
    return (password + PASSWORD_PADDING)[:32]


def extract_pdf_encryption_data(pdf_path: str):
    reader = PdfReader(pdf_path)
    encrypt = reader.trailer["/Encrypt"]

    O = encrypt["/O"]
    U = encrypt["/U"]
    P = int(encrypt["/P"])
    ID = reader.trailer["/ID"]
    document_id = ID[0].original_bytes

    return O, U, P, document_id


def derive_file_key(password_padded, O, P, document_id):
    P_bytes = struct.pack("<i", P)

    data = password_padded + O + P_bytes + document_id

    key = hashlib.md5(data).digest()

    for _ in range(50):
        key = hashlib.md5(key).digest()

    return key[:16]


def calculate_U(file_key, ID0, encrypt_metadata=True):
    data = (
        b"\x28\xbf\x4e\x5e\x4e\x75\x8a\x41"
        b"\x64\x00\x4e\x56\xff\xfa\x01\x08"
        b"\x2e\x2e\x00\xb6\xd0\x68\x3e\x80"
        b"\x2f\x0c\xa9\xfe\x64\x53\x69\x7a"
        + ID0
    )

    if not encrypt_metadata:
        data += b"\xff\xff\xff\xff"

    digest = hashlib.md5(data).digest()

    result = ARC4.new(file_key).encrypt(digest)

    for i in range(1, 20):
        key = bytes(b ^ i for b in file_key)
        result = ARC4.new(key).encrypt(result)

    return result


def main():
    # 1) password padding
    password = b"pass"  #put password here
    password_padded = pad_password(password)
    print("Padded password:", password_padded.hex())
    print("Padded length:", len(password_padded))

    # 2) extract O / U / P / ID values from the PDF
    O, U, P, document_id = extract_pdf_encryption_data("pdf.pdf") #put pdf path here
    print("\nO:", O.hex())
    print("U:", U.hex())
    print("P:", P)
    print("ID0:", document_id.hex())

    # 3) derive file key
    file_key = derive_file_key(password_padded, O, P, document_id)
    print("\nDerived file key:", file_key.hex())

    # 4) calculate U
    calculated_U = calculate_U(file_key, document_id)
    print("\nCalculated U:", calculated_U.hex())
    print("PDF U:", U.hex())
    print("Match:", calculated_U == U[:16])


if __name__ == "__main__":
    main()
