# automatically generated by the FlatBuffers compiler, do not modify

# namespace: tflite

import flatbuffers


class HashtableFindOptions(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAsHashtableFindOptions(cls, buf, offset):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = HashtableFindOptions()
        x.Init(buf, n + offset)
        return x

    # HashtableFindOptions
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)


def HashtableFindOptionsStart(builder): builder.StartObject(0)
def HashtableFindOptionsEnd(builder): return builder.EndObject()