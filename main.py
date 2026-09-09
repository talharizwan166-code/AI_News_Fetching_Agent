import logging
import sys
from src.agent import run_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    result = run_agent()
    if result["status"] == "success":
        print(f"\nDone! Posted article: {result['article']} (score: {result['score']})")
    else:
        print(f"\nAgent finished with status: {result['status']}")
        sys.exit(0)


if __name__ == "__main__":
    main()
