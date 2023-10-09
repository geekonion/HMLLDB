# The MIT License (MIT)
#
# Copyright (c) 2023 Huimao Chen
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# https://github.com/chenhuimao/HMLLDB

import lldb
from typing import Dict, List, Optional, Tuple
import HMCalculationHelper
import HMLLDBClassInfo
import HMLLDBHelpers as HM


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand('command script add -f HMDisassemble.enhanced_disassemble edisassemble -h "Enhanced disassemble"')


def enhanced_disassemble(debugger, command, exe_ctx, result, internal_dict):
    """
    Syntax:
        The syntax is the same as disassemble, please enter "help disassemble" for help.

    Examples:
        (lldb) edisassemble -s 0x107ad4504
        (lldb) edisassemble -a 0x107ad4504
        (lldb) edisassemble -n "-[NSArray objectAtIndex:]"

    This command is implemented in HMDisassemble.py
    """

    return_object = lldb.SBCommandReturnObject()
    debugger.GetCommandInterpreter().HandleCommand(f"disassemble {command}", exe_ctx, return_object)
    if return_object.GetErrorSize() > 0:
        print(return_object.GetError())
        return

    original_output = return_object.GetOutput()
    if "arm64" not in debugger.GetSelectedTarget().GetTriple():
        if return_object.GetOutputSize() > 0:
            print(original_output)
        else:
            debugger.HandleCommand(f"disassemble {command}")
        return

    # Find the starting address and the total number of addresses
    # TODO: Adapt to multiple functions
    start_address_int: int = 0
    address_count: int = 0
    assemble_lines = original_output.splitlines()
    for line in assemble_lines:
        keywords = line.split()
        if len(keywords) < 2:
            continue

        # find address
        address_str = keywords[0]
        if keywords[0] == '->':
            address_str = keywords[1]
        is_valid, address_int = HM.int_value_from_string(address_str)
        if not is_valid:
            continue
        if start_address_int == 0:
            start_address_int = address_int
        address_count += 1

    if start_address_int == 0:
        print(original_output)
        return

    # Read instructions
    target = exe_ctx.GetTarget()
    base_address: lldb.SBAddress = lldb.SBAddress(start_address_int, target)
    instruction_list: lldb.SBInstructionList = target.ReadInstructions(base_address, address_count)

    # Find instructions without comment
    address_comment_dict: Dict[int, str] = {}
    instruction_count = instruction_list.GetSize()
    for i in range(instruction_count - 1):
        instruction: lldb.SBInstruction = instruction_list.GetInstructionAtIndex(i)
        comment = instruction.GetComment(target)
        # HMLLDBClassInfo.pSBInstruction(instruction)
        if len(comment) > 0:
            continue

        # Get my comment
        if i == 0:
            my_comment = my_comment_for_instruction(instruction, None, exe_ctx)
        else:
            my_comment = my_comment_for_instruction(instruction, instruction_list.GetInstructionAtIndex(i - 1), exe_ctx)
        if len(my_comment) == 0:
            continue
        address_comment_dict[instruction.GetAddress().GetLoadAddress(target)] = my_comment

    # Print result
    for line in assemble_lines:
        keywords = line.split()
        if len(keywords) < 2:
            print(line)
            continue

        # find address
        address_str = keywords[0]
        if keywords[0] == '->':
            address_str = keywords[1]
        is_valid, address_int = HM.int_value_from_string(address_str)
        if not is_valid:
            print(line)
            continue

        if address_int in address_comment_dict:
            print(f"{line}\t\t\t\t; {address_comment_dict[address_int]}")
        else:
            print(line)


def my_comment_for_instruction(instruction: lldb.SBInstruction, previous_instruction: Optional[lldb.SBInstruction], exe_ctx: lldb.SBExecutionContext) -> str:
    target = exe_ctx.GetTarget()
    my_comment = comment_for_adrp(instruction, exe_ctx)
    if len(my_comment) > 0:
        return my_comment

    if previous_instruction is not None:
        my_comment = comment_for_adrp_next_instruction(previous_instruction, instruction, exe_ctx)
        if len(my_comment) > 0:
            return my_comment

    return ""


def comment_for_adrp(instruction: lldb.SBInstruction, exe_ctx: lldb.SBExecutionContext) -> str:
    target = exe_ctx.GetTarget()
    if instruction.GetMnemonic(target) != 'adrp':
        return ""
    operands = instruction.GetOperands(target).split(', ')
    adrp_result_tuple: Tuple[int, str] = HMCalculationHelper.calculate_adrp_result_with_immediate_and_pc_address(int(operands[1]), instruction.GetAddress().GetLoadAddress(target))
    comment = f"{operands[0]} = {adrp_result_tuple[1]}, {adrp_result_tuple[0]}"
    return comment


def comment_for_adrp_next_instruction(adrp_instruction: lldb.SBInstruction, next_instruction: lldb.SBInstruction, exe_ctx: lldb.SBExecutionContext) -> str:
    target = exe_ctx.GetTarget()
    if adrp_instruction.GetMnemonic(target) != 'adrp':
        return ""
    adrp_operands = adrp_instruction.GetOperands(target).split(', ')
    adrp_result_tuple: Tuple[int, str] = HMCalculationHelper.calculate_adrp_result_with_immediate_and_pc_address(int(adrp_operands[1]), adrp_instruction.GetAddress().GetLoadAddress(target))
    comment = ''
    mnemonic = next_instruction.GetMnemonic(target)
    operands = next_instruction.GetOperands(target).split(', ')
    if mnemonic == 'ldr':
        # adrp x2, 325020
        # ldr x2, [x2, #0x9c8]
        operands[1] = operands[1].lstrip('[')
        operands[2] = operands[2].rstrip(']')
        if adrp_operands[0] == operands[1] and operands[2].startswith('#0x'):
            load_address_int = adrp_result_tuple[0] + int(operands[2].lstrip('#'), 16)
            ldr_return_object = lldb.SBCommandReturnObject()
            lldb.debugger.GetCommandInterpreter().HandleCommand(f"x/a {load_address_int}", exe_ctx, ldr_return_object)
            load_address_output = ldr_return_object.GetOutput()
            if len(load_address_output) > 0:
                ldr_result_list = load_address_output.split(": ", 1)
                ldr_result = ldr_result_list[1]
                comment = f"{operands[0]} = {ldr_result}"

    elif mnemonic == 'ldrsw':
        # adrp x8, 61167
        # ldrsw x8, [x8, #0xaac]
        operands[1] = operands[1].lstrip('[')
        operands[2] = operands[2].rstrip(']')
        if adrp_operands[0] == operands[1] and operands[2].startswith('#0x'):
            load_address_int = adrp_result_tuple[0] + int(operands[2].lstrip('#'), 16)
            ldrsw_return_object = lldb.SBCommandReturnObject()
            lldb.debugger.GetCommandInterpreter().HandleCommand(f"x/a {load_address_int}", exe_ctx, ldrsw_return_object)
            load_address_output = ldrsw_return_object.GetOutput()
            if len(load_address_output) > 0:
                ldrsw_result_list = load_address_output.split()
                ldrsw_result = int(ldrsw_result_list[1], 16) & 0xFFFFFFFF
                if ldrsw_result & 0x80000000 > 0:
                    ldrsw_result += 0xFFFFFFFF00000000
                comment = f"{operands[0]} = {hex(ldrsw_result)}, {ldrsw_result}"

    elif mnemonic == 'add':
        # adrp x8, -24587
        # add x1, x8, #0xbbb
        if adrp_operands[0] == operands[1] and operands[2].startswith('#0x'):
            add_result = adrp_result_tuple[0] + int(operands[2].lstrip('#'), 16)
            comment = f"{operands[0]} = {hex(add_result)}, {add_result}"

    return comment

