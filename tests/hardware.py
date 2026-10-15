"""Helpers for the hardware tests (``-m hardware``)."""

from inpmap.models import OutputKind

# Product IDs of the virtual devices the hardware tests create. They differ
# from the real ones (backends/linux.py PRODUCT) because Steam remembers a
# controller's name per vendor and product ID: a test device must never give
# the user's "InpMap gamepad" a test name in Steam.
TEST_PRODUCTS = {OutputKind.KEYBOARD: 0x7E01, OutputKind.GAMEPAD: 0x7E02}


def output_backend():
    """The Linux output backend with the test product IDs."""
    from inpmap.backends.linux import LinuxOutputBackend

    return LinuxOutputBackend(products=TEST_PRODUCTS)
