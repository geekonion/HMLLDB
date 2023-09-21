# The MIT License (MIT)
#
# Copyright (c) 2020 Huimao Chen
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
from typing import Any, List, Tuple, Optional
import inspect
import HMLLDBClassInfo


g_is_first_call = True

g_class_prefixes: List[str] = []   # Class Prefixes that may be user-written
g_class_prefixes_value: lldb.SBValue = lldb.SBValue()


def process_continue() -> None:
    async_state = lldb.debugger.GetAsync()
    lldb.debugger.SetAsync(True)
    lldb.debugger.HandleCommand('process continue')
    lldb.debugger.SetAsync(async_state)


def DPrint(obj: Any) -> None:
    print('[HMLLDB] ', end='')
    print(obj)


def int_value_from_string(integer_str: str) -> Tuple[bool, int]:
    try:
        if integer_str.startswith("0x"):
            integer_value = int(integer_str, 16)
        else:
            integer_value = int(integer_str)
        return True, integer_value
    except:
        return False, 0


def evaluate_expression_value(expression: str, prefix='', print_errors=True) -> lldb.SBValue:
    frame = lldb.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()

    global g_is_first_call
    if g_is_first_call:
        g_is_first_call = False
        op = lldb.SBExpressionOptions()
        op.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
        frame.EvaluateExpression('''
            @import Foundation;
            @import UIKit;
            @import ObjectiveC;
        ''', op)

    options = lldb.SBExpressionOptions()
    # options.SetCoerceResultToId(False)
    # options.SetFetchDynamicValue(0)  # default: lldb.eNoDynamicValues 0

    # options.SetUnwindOnError(True)
    options.SetIgnoreBreakpoints(True)  # default: False
    # options.SetGenerateDebugInfo(False)

    options.SetTimeoutInMicroSeconds(5000000)  # default: 500000
    options.SetOneThreadTimeoutInMicroSeconds(4900000)  # default: 0
    # options.SetTryAllThreads(True)
    # options.SetStopOthers(True)

    options.SetTrapExceptions(False)  # default: True
    # options.SetPlaygroundTransformEnabled(False)
    # options.SetREPLMode(False)
    options.SetLanguage(lldb.eLanguageTypeObjC_plus_plus)
    options.SetSuppressPersistentResult(True)  # default: False
    if len(prefix) > 0:
        options.SetPrefix(prefix)  # default: None
    # options.SetAutoApplyFixIts(True)
    # options.SetRetriesWithFixIts(1)

    # options.SetTopLevel(False)
    # options.SetAllowJIT(True)

    value = frame.EvaluateExpression(expression, options)
    error = value.GetError()

    if print_errors and not is_successful_of_SBError(error):
        DPrint(error)
        DPrint(inspect.getframeinfo(inspect.currentframe().f_back))

    return value


# Based on https://github.com/facebook/chisel/blob/master/fblldbbase.py
def is_successful_of_SBError(err: lldb.SBError) -> bool:
    no_result = 0x1001  # 4097
    is_successful = err.success or err.value == no_result
    return is_successful


def is_SBValue_has_value(val: lldb.SBValue) -> bool:
    if val.GetValue() is None or val.GetValueAsSigned() == 0:
        return False
    return True


def bool_of_SBValue(val: lldb.SBValue) -> bool:
    result = val.GetValue()
    if result == "True" or result == "true" or result == "YES":
        return True
    return False


def add_one_shot_breakpoint_in_imp(imp: lldb.SBValue, callback_func: str, name: str) -> None:
    target = lldb.debugger.GetSelectedTarget()
    bp = target.BreakpointCreateByAddress(imp.GetValueAsUnsigned())
    bp.AddName(name)
    bp.SetOneShot(True)
    bp.SetScriptCallbackFunction(callback_func)


def get_function_address(name: str, module_name='') -> int:
    target = lldb.debugger.GetSelectedTarget()
    modules_count = target.GetNumModules()
    for i in range(modules_count):
        module = target.GetModuleAtIndex(i)
        if len(module_name) > 0:
            file_name = module.GetFileSpec().GetFilename()
            if not module_name in file_name:
                continue

        sc_list: lldb.SBSymbolContextList = module.FindFunctions(name, lldb.eFunctionNameTypeAny)
        sc_list_count = sc_list.GetSize()
        for j in range(sc_list_count):
            symbol_context = sc_list.GetContextAtIndex(j)
            address = symbol_context_get_base_range_address(symbol_context)
            if address.IsValid():
                address_int_value = address.GetLoadAddress(target)
                return address_int_value

    return 0


def symbol_context_get_base_range_address(sc: lldb.SBSymbolContext) -> lldb.SBAddress:
    # SymbolContext::GetAddressRange(...)
    base_range_address = lldb.SBAddress()
    line_entry = sc.GetLineEntry()
    block = sc.GetBlock()
    function = sc.GetFunction()
    symbol = sc.GetSymbol()

    # HMLLDBClassInfo.pSBSymbolContext(sc)
    # HMLLDBClassInfo.pSBLineEntry(line_entry)
    # HMLLDBClassInfo.pSBBlock(block)
    # HMLLDBClassInfo.pSBFunction(function)
    # HMLLDBClassInfo.pSBSymbol(symbol)

    if line_entry.IsValid():
        base_range_address = line_entry.GetStartAddress()
    elif block.IsValid():
        inline_block = block.GetContainingInlinedBlock()
        if inline_block.IsValid():
            base_range_address = inline_block.GetRangeStartAddress(0)
    elif function.IsValid():
        base_range_address = function.GetStartAddress()
    elif symbol.IsValid():
        base_range_address = symbol.GetStartAddress()

    return base_range_address


def get_module_name_from_address(address_str: str) -> Optional[str]:
    is_valid, address_int = int_value_from_string(address_str)
    if not is_valid:
        return "Invalid address"
    address: lldb.SBAddress = lldb.SBAddress(address_int, lldb.debugger.GetSelectedTarget())
    return address.GetModule().GetFileSpec().GetFilename()


def get_class_prefixes() -> Tuple[List[str], lldb.SBValue]:
    global g_class_prefixes
    global g_class_prefixes_value

    if is_SBValue_has_value(g_class_prefixes_value):
        return g_class_prefixes, g_class_prefixes_value

    DPrint("Getting class prefixes when using this function for the first time")

    command_script = '''
        unsigned int classCount;
        Class *classList = objc_copyClassList(&classCount);
        NSMutableArray *clsPrefixes = [[NSMutableArray alloc] init];
        for (int i = 0; i < classCount; i++) {
            NSString *name = [[NSString alloc] initWithUTF8String:class_getName(classList[i])];
            if ([name containsString:@"."]) {
                NSRange range = [name rangeOfString:@"."];
                NSString *prefix = [name substringToIndex:range.location];
                if (![clsPrefixes containsObject:prefix] && ![prefix containsString:@"NSKVONotifying_"] && ![prefix containsString:@"_NSZombie_"]) {
                    [clsPrefixes addObject:prefix];
                }
            }
        }
        free(classList);
        (NSMutableArray *)clsPrefixes;
    '''

    g_class_prefixes_value = evaluate_expression_value(command_script)
    for i in range(g_class_prefixes_value.GetNumChildren()):
        prefix_value = g_class_prefixes_value.GetChildAtIndex(i)
        g_class_prefixes.append(prefix_value.GetObjectDescription())

    return g_class_prefixes, g_class_prefixes_value


def is_existing_class(class_name: str) -> bool:
    command_script = f'''
        Class cls = (Class)objc_lookUpClass("{class_name}");
        BOOL exist = NO;
        if (cls) {{
            exist = YES;
        }}
        (BOOL)exist;
    '''

    value = evaluate_expression_value(command_script)
    return bool_of_SBValue(value)


def is_existing_protocol(protocol_name: str) -> bool:
    command_script = f'''
        BOOL exist = NO;
        Protocol *targetProtocol = (Protocol *)objc_getProtocol("{protocol_name}");
        if (targetProtocol) {{
            exist = YES;
        }}
        (BOOL)exist;
    '''
    value = evaluate_expression_value(command_script)
    return bool_of_SBValue(value)


def allocate_class(class_name: str, super_class_name: str) -> lldb.SBValue:
    command_script = f'''
        Class newCls = (Class)objc_lookUpClass("{class_name}");
        if (!newCls) {{
            Class superCls = (Class)objc_lookUpClass("{super_class_name}");
            newCls = (Class)objc_allocateClassPair(superCls, "{class_name}", 0);
        }}
        (Class)newCls;
    '''

    return evaluate_expression_value(command_script)


def register_class(class_address: str) -> None:
    command_script = f"(void)objc_registerClassPair(Class({class_address}))"
    evaluate_expression_value(command_script)


def add_ivar(class_address: str, ivar_name: str, types: str) -> bool:
    command_script = f'''
        const char * types = @encode({types});
        NSUInteger size;
        NSUInteger alingment;
        NSGetSizeAndAlignment(types, &size, &alingment);
        (BOOL)class_addIvar((Class){class_address}, "{ivar_name}", size, alingment, types);
    '''

    value = evaluate_expression_value(command_script)
    return bool_of_SBValue(value)


def add_class_method(class_name: str, selector: str, imp_address: str, types: str) -> None:
    command_script = f'''
        Class metaCls = (Class)objc_getMetaClass("{class_name}");
        if (metaCls) {{
            SEL selector = NSSelectorFromString([[NSString alloc] initWithUTF8String:"{selector}"]);
            (BOOL)class_addMethod(metaCls, selector, (void (*)()){imp_address}, "{types}");
        }}
    '''

    evaluate_expression_value(command_script)


def add_instance_method(class_name: str, selector: str, imp_address: str, types: str) -> None:
    command_script = f'''
        Class cls = (Class)objc_lookUpClass("{class_name}");
        if (cls) {{
            SEL selector = NSSelectorFromString([[NSString alloc] initWithUTF8String:"{selector}"]);
            (BOOL)class_addMethod(cls, selector, (void (*)()){imp_address}, "{types}");
        }}
    '''

    evaluate_expression_value(command_script)
