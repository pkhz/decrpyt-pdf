from pypdf import PdfReader

try:
    reader = PdfReader("pdf.pdf") #put pdf path here
    print("1")

    print("Encrypted:", reader.is_encrypted)

    if reader.is_encrypted:
        print("2")
        encrypt = reader.trailer["/Encrypt"]

        print("Filter:", encrypt.get("/Filter"))
        print("V:", encrypt.get("/V"))
        print("R:", encrypt.get("/R"))
        print("Length:", encrypt.get("/Length"))
        print("CF:", encrypt.get("/CF"))
        print("StmF:", encrypt.get("/StmF"))
        print("StrF:", encrypt.get("/StrF"))

except Exception as e:
    print("Error:", e)