# Excerpt from hbldh/bleak v0.22.3, bleak/__init__.py, start_notify method.
# Parent file Git blob: 68e178125cf28848dc83440f52acc0dc80f96ca4.
# Only class indentation is removed. See BLEAK_LICENSE.txt.
async def start_notify(
    self,
    char_specifier: Union[BleakGATTCharacteristic, int, str, uuid.UUID],
    callback: Callable[
        [BleakGATTCharacteristic, bytearray], Union[None, Awaitable[None]]
    ],
    **kwargs,
) -> None:
    """
    Activate notifications/indications on a characteristic.

    Callbacks must accept two inputs. The first will be the characteristic
    and the second will be a ``bytearray`` containing the data received.

    .. code-block:: python

        def callback(sender: BleakGATTCharacteristic, data: bytearray):
            print(f"{sender}: {data}")

        client.start_notify(char_uuid, callback)

    Args:
        char_specifier:
            The characteristic to activate notifications/indications on a
            characteristic, specified by either integer handle,
            UUID or directly by the BleakGATTCharacteristic object representing it.
        callback:
            The function to be called on notification. Can be regular
            function or async function.


    .. versionchanged:: 0.18
        The first argument of the callback is now a :class:`BleakGATTCharacteristic`
        instead of an ``int``.
    """
    if not self.is_connected:
        raise BleakError("Not connected")

    if not isinstance(char_specifier, BleakGATTCharacteristic):
        characteristic = self.services.get_characteristic(char_specifier)
    else:
        characteristic = char_specifier

    if not characteristic:
        raise BleakCharacteristicNotFoundError(char_specifier)

    if inspect.iscoroutinefunction(callback):

        def wrapped_callback(data: bytearray) -> None:
            task = asyncio.create_task(callback(characteristic, data))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    else:
        wrapped_callback = functools.partial(callback, characteristic)

    await self._backend.start_notify(characteristic, wrapped_callback, **kwargs)
