# automatically generated by the FlatBuffers compiler, do not modify

# namespace: tflite

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()


class BitwiseXorOptions(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAsBitwiseXorOptions(cls, buf, offset):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = BitwiseXorOptions()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def BitwiseXorOptionsBufferHasIdentifier(cls, buf, offset, size_prefixed=False):
        return flatbuffers.util.BufferHasIdentifier(buf, offset, b"\x54\x46\x4C\x33", size_prefixed=size_prefixed)

    # BitwiseXorOptions
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)


def BitwiseXorOptionsStart(builder): builder.StartObject(0)
def BitwiseXorOptionsEnd(builder): return builder.EndObject()
