import logging
import sys
import tkinter as tk

from find_duplicate_images.gui import DuplicateImageFinderGUI

logger = logging.getLogger(__name__)


def main():
    # Without a handler configured, every logger.* call in this package is
    # discarded and crashes below would report nothing.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        root = tk.Tk()
        DuplicateImageFinderGUI(root)
        root.mainloop()

    except KeyboardInterrupt:
        logger.info("Application interrupted by user.")
        sys.exit(0)

    except Exception:
        logger.exception("An unexpected error occurred")
        sys.exit(1)


if __name__ == "__main__":
    main()
