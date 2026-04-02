import subprocess
import sys
import os

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print("=" * 50)
    print("    NBA Stats - Iniciando Aplicacao")
    print("=" * 50)
    print()
    
    print("[1/1] Iniciando Streamlit (Frontend)...")
    print("      Acesse: http://localhost:8501")
    print()
    
    subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])

if __name__ == "__main__":
    main()