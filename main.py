from pypdf import PdfReader, PdfWriter


def check_password(pdf_path, password):
    reader = PdfReader(pdf_path)

    if not reader.is_encrypted:
        return True

    result = reader.decrypt(password)

    return result != 0


def decrypt_pdf(pdf_path, password, output_path):
    reader = PdfReader(pdf_path)

    if reader.is_encrypted:
        result = reader.decrypt(password)

        if result == 0:
            raise ValueError("Incorrect password")

    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)