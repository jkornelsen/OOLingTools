# -*- coding: Latin-1 -*-
#
# This file created February 22 2016 by Jim Kornelsen
#
# 15-Dec-2017 JDK  Added Exception.

"""
A fake UNO file needed to make PyLint happy.
www.openoffice.org/api/docs/common/ref/com/sun/star/uno/module-ix.html
"""

_PyException = Exception  # This is the normal python Exception class.

class Exception(_PyException):
    """Not the same as the normal Exception class, which makes it confusing.
    Perhaps they should have used a different name.
    """
    pass

class RuntimeException(_PyException):
    pass

