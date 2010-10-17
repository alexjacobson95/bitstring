#!/usr/bin/env python

import copy
import os

class BaseArray(object):
    """Array types should implement the methods given here."""

    __slots__ = ()

    def __init__(self, data, bitlength=0, offset=0):
        raise NotImplementedError

    def getbit(self, pos):
        """Return the bit at pos (True or False)."""
        raise NotImplementedError

    def getbyte(self, pos):
        """Return the integer value of the byte stored at pos."""
        raise NotImplementedError

    def getbyteslice(self, start, end):
        """Return a byte slice"""
        raise NotImplementedError

    def __copy__(self):
        raise NotImplementedError

    def setoffset(self, newoffset):
        raise NotImplementedError

    def appendarray(self, array):
        raise NotImplementedError

    def prependarray(self, array):
        raise NotImplementedError


class ConstByteArray(BaseArray):
    """Stores raw bytes together with a bit offset and length."""

    __slots__ = ('offset', '_rawarray', 'bitlength')

    def __init__(self, data, bitlength=0, offset=0):
        assert isinstance(data, bytearray)
        self._rawarray = data
        self.offset = offset
        self.bitlength = bitlength

    def __copy__(self):
        return ByteArray(self._rawarray[:], self.bitlength, self.offset)

    def getbit(self, pos):
        assert 0 <= pos < self.bitlength
        byte, bit = divmod(self.offset + pos, 8)
        return bool(self._rawarray[byte] & (128 >> bit))

    def getbyte(self, pos):
        return self._rawarray[pos + self.byteoffset]

    def getbyteslice(self, start, end):
        c = self._rawarray[start + self.byteoffset:end + self.byteoffset]
        return c

    @property
    def bytelength(self):
        if self.bitlength == 0:
            return 0
        sb = self.offset // 8
        eb = (self.offset + self.bitlength - 1) // 8
        if eb == -1:
            return 1 # ? Empty bitstring still has one byte of data?
        return eb - sb + 1
    
    @property
    def byteoffset(self):
        return self.offset // 8

    @property
    def rawbytes(self):
        return self._rawarray


class ByteArray(ConstByteArray):
    
    __slots__ = ()
    
    def setbit(self, pos):
        assert 0 <= pos < self.bitlength
        byte, bit = divmod(self.offset + pos, 8)
        self._rawarray[byte] |= (128 >> bit)

    def unsetbit(self, pos):
        assert 0 <= pos < self.bitlength
        byte, bit = divmod(self.offset + pos, 8)
        self._rawarray[byte] &= ~(128 >> bit)
        
    def invertbit(self, pos):
        assert 0 <= pos < self.bitlength
        byte, bit = divmod(self.offset + pos, 8)
        self._rawarray[byte] ^= (128 >> bit)

    def setbyte(self, pos, value):
        self._rawarray[pos + self.byteoffset] = value

    def setbyteslice(self, start, end, value):
        self._rawarray[start + self.byteoffset:end + self.byteoffset] = value

    def appendarray(self, array):
        """Join another array on to the end of this one."""
        if array.bitlength == 0:
            return
        # Set new array offset to the number of bits in the final byte of current array.
        array = offsetcopy(array, (self.offset + self.bitlength) % 8)
        if array.offset != 0:
            # first do the byte with the join.
            joinval = (self._rawarray.pop() & (255 ^ (255 >> array.offset)) | (array.getbyte(0) & (255 >> array.offset)))
            self._rawarray.append(joinval)
            self._rawarray.extend(array._rawarray[1:])
        else:
            self._rawarray.extend(array._rawarray)
        self.bitlength += array.bitlength

    def prependarray(self, array):
        """Join another array on to the start of this one."""
        if array.bitlength == 0:
            return
        # Set the offset of copy of array so that it's final byte
        # ends in a position that matches the offset of self,
        # then join self on to the end of it.
        array = offsetcopy(array, (self.offset - array.bitlength) % 8)
        assert (array.offset + array.bitlength) % 8 == self.offset
        if self.offset != 0:
            # first do the byte with the join.
            array.setbyte(-1, (array.getbyte(-1) & (255 ^ (255 >> self.offset)) | \
                                   (self._rawarray[0] & (255 >> self.offset))))
            array._rawarray.extend(self._rawarray[1 : self.bytelength])
        else:
            array._rawarray.extend(self._rawarray[0 : self.bytelength])
        self._rawarray = array._rawarray
        self.offset = array.offset
        self.bitlength += array.bitlength
    

class FileArray(BaseArray):
    """A class that mimics bytearray but gets data from a file object."""

    __slots__ = ('source', 'bytelength', 'bitlength', 'byteoffset', 'offset')

    def __init__(self, source, bitlength, offset):
        # byteoffset - bytes to ignore at start of file
        # bitoffset - bits (0-7) to ignore after the byteoffset
        byteoffset, bitoffset = divmod(offset, 8)
        filelength = os.path.getsize(source.name)
        self.source = source
        if bitlength is None:
            self.bytelength = filelength - byteoffset
            bitlength = self.bytelength*8 - bitoffset
        else:
            self.bytelength = (bitlength + bitoffset + 7) // 8
        if self.bytelength > filelength - byteoffset:
            from bitstring import CreationError
            raise CreationError("File is not long enough for specified "
                                "bitstring length and offset.")
        self.byteoffset = byteoffset
        self.bitlength = bitlength
        self.offset = bitoffset

    def __copy__(self):
        # Asking for a copy of a FileArray gets you a MemArray. After all,
        # why would you want a copy if you didn't want to modify it?
        return ByteArray(self.rawbytes, self.bitlength, self.offset)

    def __getitem__(self, pos):
        # This is to allow offsetcopy to index like it does the
        # _rawarray of the ByteArray
        return self.getbyte(pos + self.byteoffset)
        
    def getbyte(self, pos):
        if pos < 0:
            pos += self.bytelength
        pos += self.byteoffset
        self.source.seek(pos, os.SEEK_SET)
        return ord(self.source.read(1))

    def getbit(self, pos):
        assert 0 <= pos < self.bitlength
        byte, bit = divmod(self.offset + pos, 8)
        byte += self.byteoffset
        self.source.seek(byte, os.SEEK_SET)
        return bool(ord(self.source.read(1)) & (128 >> bit))

    def getbyteslice(self, start, end):
        if start < end:
            self.source.seek(start + self.byteoffset, os.SEEK_SET)
            return bytearray(self.source.read(end - start))
        else:
            return bytearray()

    @property
    def rawbytes(self):
        return bytearray(self.getbyteslice(0, self.bytelength))
        
def slice(ba, bitlength, offset):
    """Return a new ByteArray created as a slice of ba."""
    try:
        return ByteArray(ba._rawarray, bitlength, ba.offset + offset)
    except AttributeError:
        return FileArray(ba.source, bitlength, 8*ba.byteoffset + ba.offset + offset)
        
def offsetcopy(s, newoffset):
    """Return a copy of s with the newoffset."""
    assert 0 <= newoffset < 8
    if s.bitlength == 0:
        return copy.copy(s)
    else:
        assert 0 <= newoffset < 8
        newdata = []
        try:
            d = s._rawarray
        except AttributeError:
            d = s
        if newoffset == s.offset % 8:
            new_s = ByteArray(s.getbyteslice(0, s.bytelength), s.bitlength, newoffset)
            return new_s
        assert newoffset != s.offset % 8
        if newoffset < s.offset % 8:
            # We need to shift everything left
            shiftleft = s.offset % 8 - newoffset
            # First deal with everything except for the final byte
            for x in range(s.byteoffset, s.byteoffset + s.bytelength - 1):
                newdata.append(((d[x] << shiftleft) & 0xff) + \
                                     (d[x + 1] >> (8 - shiftleft)))
            bits_in_last_byte = (s.offset + s.bitlength) % 8
            if bits_in_last_byte == 0:
                bits_in_last_byte = 8
            if bits_in_last_byte > shiftleft:
                newdata.append((d[s.byteoffset + s.bytelength - 1] << shiftleft) & 0xff)
        else: # newoffset > s._offset % 8
            shiftright = newoffset - s.offset % 8
            newdata.append(s.getbyte(0) >> shiftright)
            for x in range(1, s.bytelength):
                newdata.append(((d[x-1] << (8 - shiftright)) & 0xff) + \
                                     (d[x] >> shiftright))
            bits_in_last_byte = (s.offset + s.bitlength) % 8
            if bits_in_last_byte == 0:
                bits_in_last_byte = 8
            if bits_in_last_byte + shiftright > 8:
                newdata.append((d[s.byteoffset + s.bytelength - 1] << (8 - shiftright)) & 0xff)
        new_s = ByteArray(bytearray(newdata), s.bitlength, newoffset)
        assert new_s.offset == newoffset
        return new_s
    
def equal(a, b):
    """Return True if a == b."""
    
    a_bitlength = a.bitlength
    b_bitlength = b.bitlength
    if a_bitlength != b_bitlength:
        return False
    if a_bitlength == 0:
        return True
    # Make 'a' the one with the smaller offset
    if (a.offset % 8) > (b.offset % 8):
        a, b = b, a
    a_bitoff = a.offset % 8
    b_bitoff = b.offset % 8
    a_byteoffset = a.byteoffset
    b_byteoffset = b.byteoffset
    a_bytelength = a.bytelength
    b_bytelength = b.bytelength
    
    try:
        da = a._rawarray
        db = b._rawarray
    except AttributeError:
        da = a
        db = b
        
    # If they are pointing to the same data, they must be equal
    if da is db and a.offset == b.offset:
        return True
        
    if a_bitoff == b_bitoff:
        bits_spare_in_last_byte = 8 - (a_bitoff + a_bitlength) % 8
        if bits_spare_in_last_byte == 8:
            bits_spare_in_last_byte = 0
        # Special case for a, b contained in a single byte
        if a_bytelength == 1:
            a_val = ((da[a_byteoffset] << a_bitoff) & 0xff) >> (8 - a_bitlength)
            b_val = ((db[b_byteoffset] << b_bitoff) & 0xff) >> (8 - b_bitlength)
            return a_val == b_val
        # Otherwise check first byte
        if da[a_byteoffset] & (0xff >> a_bitoff) != db[b_byteoffset] & (0xff >> b_bitoff):
            return False
        # then everything up to the last
        b_a_offset = b_byteoffset - a_byteoffset
        for x in range(1 + a_byteoffset, a_byteoffset + a_bytelength - 1):
            if da[x] != db[b_a_offset + x]:
                return False
        # and finally the last byte
        if da[a_byteoffset + a_bytelength - 1] >> bits_spare_in_last_byte != db[b_byteoffset + b_bytelength - 1] >> bits_spare_in_last_byte:
            return False
        return True

    # This is how much we need to shift a to the right to compare with b:
    shift = b_bitoff - a_bitoff
    # Special case for b only one byte long
    if b_bytelength == 1:
        assert a_bytelength == 1
        a_val = ((da[a_byteoffset] << a_bitoff) & 0xff) >> (8 - a_bitlength)
        b_val = ((db[b_byteoffset] << b_bitoff) & 0xff) >> (8 - b_bitlength)
        return a_val == b_val
    # Special case for a only one byte long
    if a_bytelength == 1:
        assert b_bytelength == 2
        a_val = ((da[a_byteoffset] << a_bitoff) & 0xff) >> (8 - a_bitlength)
        b_val = db[b_byteoffset] << 8
        b_val += db[b_byteoffset + 1]
        b_val <<= b_bitoff
        b_val &= 0xffff
        b_val >>= 16 - b_bitlength
        return a_val == b_val
    
    # Compare first byte of b with bits from first byte of a
    if (da[a_byteoffset] & (0xff >> a_bitoff)) >> shift != db[b_byteoffset] & (0xff >> b_bitoff):
        return False
    # Now compare every full byte of b with bits from 2 bytes of a
    for x in range(1, b_bytelength - 1):
        # Construct byte from 2 bytes in a to compare to byte in b
        b_val = db[b_byteoffset + x]
        a_val = da[a_byteoffset + x - 1] << 8
        a_val += da[a_byteoffset + x]
        a_val >>= shift
        a_val &= 0xff
        if a_val != b_val:
            return False
    
    # Now check bits in final byte of b
    final_b_bits = (b.offset + b_bitlength) % 8
    if final_b_bits == 0:
        final_b_bits = 8
    b_val = db[b_byteoffset + b_bytelength - 1] >> (8 - final_b_bits)
    final_a_bits = (a.offset + a_bitlength) % 8
    if final_a_bits == 0:
        final_a_bits = 8
    if b.bytelength > a_bytelength:
        assert b_bytelength == a_bytelength + 1
        a_val = da[a_byteoffset + a_bytelength - 1] >> (8 - final_a_bits)
        a_val &= 0xff >> (8 - final_b_bits)
        return a_val == b_val
    assert a_bytelength == b_bytelength
    a_val = da[a_byteoffset + a_bytelength - 2] << 8
    a_val += da[a_byteoffset + a_bytelength - 1]
    a_val >>= (8 - final_a_bits)
    a_val &= 0xff >> (8 - final_b_bits)
    return a_val == b_val
    
    
        