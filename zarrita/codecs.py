from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Tuple, Union

import numpy as np
from attr import asdict, frozen
from cattrs import register_structure_hook, structure
from numcodecs.blosc import Blosc
from numcodecs.gzip import GZip

from zarrita.sharding import ShardingCodecConfigurationMetadata, ShardingCodecMetadata
from zarrita.value_handle import ArrayHandle, BufferHandle, NoneHandle, ValueHandle

if TYPE_CHECKING:
    from zarrita.array import CoreArrayMetadata


def _needs_bytes(
    f: Callable[[Any, bytes, Tuple[slice, ...], "CoreArrayMetadata"], ValueHandle]
) -> Callable[[Any, ValueHandle, Tuple[slice, ...], "CoreArrayMetadata"], ValueHandle]:
    def inner(
        _self,
        value: ValueHandle,
        selection: Tuple[slice, ...],
        array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        buf = value.tobytes()
        if buf is None:
            return NoneHandle()
        return f(_self, buf, selection, array_metadata)

    return inner


def _needs_array(
    f: Callable[[Any, np.ndarray, Tuple[slice, ...], "CoreArrayMetadata"], ValueHandle]
) -> Callable[[Any, ValueHandle, Tuple[slice, ...], "CoreArrayMetadata"], ValueHandle]:
    def inner(
        _self,
        value: ValueHandle,
        selection: Tuple[slice, ...],
        array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        array = value.toarray()
        if array is None:
            return NoneHandle()
        return f(_self, array, selection, array_metadata)

    return inner


@frozen
class BloscCodecConfigurationMetadata:
    cname: Literal["lz4", "lz4hc", "blosclz", "zstd", "snappy", "zlib"] = "zstd"
    clevel: int = 5
    shuffle: Literal["noshuffle", "shuffle", "bitshuffle"] = "noshuffle"
    blocksize: int = 0


@frozen
class BloscCodecMetadata:
    configuration: BloscCodecConfigurationMetadata
    name: Literal["blosc"] = "blosc"

    def _get_blosc_codec(self):
        d = asdict(self.configuration)
        map_shuffle_str_to_int = {
            "noshuffle": 0,
            "shuffle": 1,
            "bitshuffle": 2
        }
        d["shuffle"] = map_shuffle_str_to_int[d["shuffle"]]
        return Blosc.from_config(d)

    @_needs_bytes
    def decode(
        self,
        buf: bytes,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        return BufferHandle(self._get_blosc_codec().decode(buf))

    @_needs_array
    def encode(
        self,
        chunk: np.ndarray,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        if not chunk.flags.c_contiguous and not chunk.flags.f_contiguous:
            chunk = chunk.copy(order="K")
        return BufferHandle(self._get_blosc_codec().encode(chunk))


@frozen
class EndianCodecConfigurationMetadata:
    endian: Literal["big", "little"] = "little"


@frozen
class EndianCodecMetadata:
    configuration: EndianCodecConfigurationMetadata
    name: Literal["endian"] = "endian"

    def _get_byteorder(self, array: np.ndarray) -> Literal["big", "little"]:
        if array.dtype.byteorder == "<":
            return "little"
        elif array.dtype.byteorder == ">":
            return "big"
        else:
            import sys

            return sys.byteorder

    @_needs_array
    def decode(
        self,
        chunk: np.ndarray,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        byteorder = self._get_byteorder(chunk)
        if self.configuration.endian != byteorder:
            chunk = chunk.view(dtype=chunk.dtype.newbyteorder(byteorder))
        return ArrayHandle(chunk)

    @_needs_array
    def encode(
        self,
        chunk: np.ndarray,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        byteorder = self._get_byteorder(chunk)
        if self.configuration.endian != byteorder:
            chunk = chunk.view(dtype=chunk.dtype.newbyteorder(byteorder))
        return ArrayHandle(chunk)


@frozen
class TransposeCodecConfigurationMetadata:
    order: Union[Literal["C", "F"], Tuple[int, ...]] = "C"


@frozen
class TransposeCodecMetadata:
    configuration: TransposeCodecConfigurationMetadata
    name: Literal["transpose"] = "transpose"

    @_needs_array
    def decode(
        self,
        chunk: np.ndarray,
        _selection: Tuple[slice, ...],
        array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        new_order = self.configuration.order
        chunk = chunk.view(np.dtype(array_metadata.data_type.value))
        if isinstance(new_order, tuple):
            chunk = chunk.transpose(new_order)
        else:
            chunk = chunk.reshape(
                array_metadata.chunk_shape,
                order=new_order,
            )
        return ArrayHandle(chunk)

    @_needs_array
    def encode(
        self,
        chunk: np.ndarray,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        new_order = self.configuration.order
        if isinstance(new_order, tuple):
            chunk = chunk.reshape(-1, order="C")
        else:
            chunk = chunk.reshape(-1, order=new_order)
        return ArrayHandle(chunk)


@frozen
class GzipCodecConfigurationMetadata:
    level: int = 5


@frozen
class GzipCodecMetadata:
    configuration: GzipCodecConfigurationMetadata
    name: Literal["gzip"] = "gzip"

    @_needs_bytes
    def decode(
        self,
        buf: bytes,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        return BufferHandle(GZip(self.configuration.level).decode(buf))

    @_needs_bytes
    def encode(
        self,
        buf: bytes,
        _selection: Tuple[slice, ...],
        _array_metadata: "CoreArrayMetadata",
    ) -> ValueHandle:
        return BufferHandle(GZip(self.configuration.level).encode(buf))


CodecMetadata = Union[
    BloscCodecMetadata,
    EndianCodecMetadata,
    TransposeCodecMetadata,
    GzipCodecMetadata,
    ShardingCodecMetadata,
]


def blosc_codec(
    cname: Literal["lz4", "lz4hc", "blosclz", "zstd", "snappy", "zlib"] = "zstd",
    clevel: int = 5,
    shuffle: Literal["noshuffle", "shuffle", "bitshuffle"] = "noshuffle",
    blocksize: int = 0,
) -> BloscCodecMetadata:
    return BloscCodecMetadata(
        configuration=BloscCodecConfigurationMetadata(
            cname=cname, clevel=clevel, shuffle=shuffle, blocksize=blocksize
        )
    )


def endian_codec(endian: Literal["big", "little"]) -> EndianCodecMetadata:
    return EndianCodecMetadata(configuration=EndianCodecConfigurationMetadata(endian))


def transpose_codec(
    order: Union[Tuple[int, ...], Literal["C", "F"]]
) -> TransposeCodecMetadata:
    return TransposeCodecMetadata(
        configuration=TransposeCodecConfigurationMetadata(order)
    )


def gzip_codec(level: int = 5) -> GzipCodecMetadata:
    return GzipCodecMetadata(configuration=GzipCodecConfigurationMetadata(level))


def sharding_codec(
    chunk_shape: Tuple[int, ...], codecs: List[CodecMetadata] = []
) -> ShardingCodecMetadata:
    return ShardingCodecMetadata(
        configuration=ShardingCodecConfigurationMetadata(chunk_shape, codecs)
    )
