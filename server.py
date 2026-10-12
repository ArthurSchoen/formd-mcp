from fastmcp import FastMCP
mcp = FastMCP("formd")

@mcp.tool
def ping():
    "Vérifie que le serveur Form D répond."
    return "pong"

if __name__ == "__main__":
    mcp.run() 


