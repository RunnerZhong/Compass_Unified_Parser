# automatically generated by the FlatBuffers compiler, do not modify

# namespace: tflite

import flatbuffers


class CosOptions(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAsCosOptions(cls, buf, offset):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = CosOptions()
        x.Init(buf, n + offset)
        return x

    # CosOptions
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)


def CosOptionsStart(builder): builder.StartObject(0)
def CosOptionsEnd(builder): return builder.EndObject()