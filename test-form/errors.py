class Unavailable(Exception):
    """Provider definitively rejected contact; safe to try next channel."""
class Uncertain(Exception):
    """Stop: provider outcome is not known."""
