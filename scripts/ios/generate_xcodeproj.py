#!/usr/bin/env python3
"""Generate the PatientApp Xcode project using only the repository toolchain."""

from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import textwrap


ROOT = pathlib.Path(__file__).resolve().parents[2]
IOS = ROOT / "apps" / "ios"
PROJECT = IOS / "PatientApp.xcodeproj"
SCHEMES = PROJECT / "xcshareddata" / "xcschemes"


def uid(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()[:24].upper()


def q(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def fs_group(label: str, path: str) -> tuple[str, str]:
    identifier = uid(f"group:{label}")
    return identifier, textwrap.dedent(f"""\
        {identifier} /* {label} */ = {{
            isa = PBXFileSystemSynchronizedRootGroup;
            path = {q(path)};
            sourceTree = \"<group>\";
        }};
    """)


def phase(identifier: str, isa_name: str, name: str, files: list[str] | None = None) -> str:
    entries = "\n".join(f"\t\t\t{item}," for item in files or [])
    return textwrap.dedent(f"""\
        {identifier} /* {name} */ = {{
            isa = {isa_name};
            buildActionMask = 2147483647;
            files = (
        {entries}
            );
            runOnlyForDeploymentPostprocessing = 0;
        }};
    """)


def file_ref(identifier: str, label: str, path: str, file_type: str) -> str:
    return textwrap.dedent(f"""\
        {identifier} /* {label} */ = {{
            isa = PBXFileReference;
            explicitFileType = {file_type};
            includeInIndex = 0;
            path = {q(path)};
            sourceTree = \"<group>\";
        }};
    """)


def build_file(identifier: str, ref: str, label: str) -> str:
    return f"\t\t{identifier} /* {label} */ = {{isa = PBXBuildFile; fileRef = {ref} /* {label} */;}};\n"


def embedded_build_file(identifier: str, ref: str, label: str) -> str:
    return textwrap.dedent(f"""\
        {identifier} /* {label} */ = {{
            isa = PBXBuildFile;
            fileRef = {ref} /* {label} */;
            settings = {{
                ATTRIBUTES = (
                    CodeSignOnCopy,
                    RemoveHeadersOnCopy,
                );
            }};
        }};
    """)


def copy_phase(identifier: str, name: str, files: list[str]) -> str:
    entries = "\n".join(f"\t\t\t{item}," for item in files)
    return textwrap.dedent(f"""\
        {identifier} /* {name} */ = {{
            isa = PBXCopyFilesBuildPhase;
            buildActionMask = 2147483647;
            dstPath = "";
            dstSubfolderSpec = 10;
            files = (
        {entries}
            );
            name = {q(name)};
            runOnlyForDeploymentPostprocessing = 0;
        }};
    """)


def config(identifier: str, name: str, settings: dict[str, str]) -> str:
    lines = "\n".join(f"\t\t\t\t{key} = {value};" for key, value in sorted(settings.items()))
    return textwrap.dedent(f"""\
        {identifier} /* {name} */ = {{
            isa = XCBuildConfiguration;
            buildSettings = {{
        {lines}
            }};
            name = {q(name)};
        }};
    """)


def config_list(identifier: str, debug: str, release: str, label: str) -> str:
    return textwrap.dedent(f"""\
        {identifier} /* Build configuration list for {label} */ = {{
            isa = XCConfigurationList;
            buildConfigurations = (
                {debug} /* Debug */,
                {release} /* Release */,
            );
            defaultConfigurationIsVisible = 0;
            defaultConfigurationName = Release;
        }};
    """)


def target(identifier: str, name: str, product_ref: str, product_type: str,
           config_id: str, build_phases: list[str], groups: list[str], deps: list[str]) -> str:
    phases = "\n".join(f"\t\t\t\t{item}," for item in build_phases)
    synced = "\n".join(f"\t\t\t\t{item} /* {name} sources */," for item in groups)
    dependencies = "\n".join(f"\t\t\t\t{item}," for item in deps)
    group_block = f"\n            fileSystemSynchronizedGroups = (\n{synced}\n            );" if groups else ""
    return textwrap.dedent(f"""\
        {identifier} /* {name} */ = {{
            isa = PBXNativeTarget;
            buildConfigurationList = {config_id} /* Build configuration list for {name} */;
            buildPhases = (
        {phases}
            );
            buildRules = (
            );
            dependencies = (
        {dependencies}
            );{group_block}
            name = {q(name)};
            productName = {q(name)};
            productReference = {product_ref} /* product */;
            productType = {q(product_type)};
        }};
    """)


def target_settings(bundle_id: str, product_name: str, *, app: bool = False, test: bool = False, ui_test: bool = False) -> dict[str, str]:
    settings = {
        "CLANG_ENABLE_MODULES": "YES",
        "CURRENT_PROJECT_VERSION": "1",
        "DEFINES_MODULE": "YES",
        "ENABLE_TESTABILITY": "YES",
        "GCC_C_LANGUAGE_STANDARD": "gnu17",
        "GCC_WARN_INHIBIT_ALL_WARNINGS": "NO",
        "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "LD_RUNPATH_SEARCH_PATHS": q("$(inherited) @executable_path/Frameworks @loader_path/Frameworks"),
        "MARKETING_VERSION": "0.1.0",
        "PRODUCT_BUNDLE_IDENTIFIER": q(bundle_id),
        "PRODUCT_NAME": q(product_name),
        "SDKROOT": "iphoneos",
        "SWIFT_EMIT_LOC_STRINGS": "YES",
        "SWIFT_STRICT_CONCURRENCY": "minimal",
        "SWIFT_VERSION": "6.0",
        "TARGETED_DEVICE_FAMILY": q("1,2"),
    }
    if app:
        settings.update({
            "DEVELOPMENT_TEAM": "QH6389JMZY",
            "GENERATE_INFOPLIST_FILE": "NO",
            "INFOPLIST_FILE": q("Resources/Info.plist"),
            "INFOPLIST_KEY_CFBundleDisplayName": q("Patient App"),
            "INFOPLIST_KEY_LSApplicationCategoryType": q("public.app-category.medical"),
            "PRODUCT_MODULE_NAME": q("PatientApp"),
            "SUPPORTED_PLATFORMS": q("iphoneos iphonesimulator"),
        })
    if ui_test:
        settings.update({
            "TEST_TARGET_NAME": q("PatientApp"),
        })
    elif not test:
        settings["LD_DYLIB_INSTALL_NAME"] = q("@rpath/$(PRODUCT_NAME).framework/$(PRODUCT_NAME)")
    settings["SWIFT_ENABLE_EXPLICIT_MODULES"] = "NO"
    if test or not app:
        settings["GENERATE_INFOPLIST_FILE"] = "YES"
    return settings


def project_settings() -> dict[str, str]:
    return {
        "CLANG_ENABLE_MODULES": "YES",
        "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "MARKETING_VERSION": "0.1.0",
        "CURRENT_PROJECT_VERSION": "1",
        "SWIFT_VERSION": "6.0",
    }


def scheme(project_targets: dict[str, str], test_targets: list[str]) -> str:
    app_id = project_targets["PatientApp"]
    build_test_entries = "\n".join(
        f'''      <BuildActionEntry buildForTesting = "YES" buildForRunning = "NO" buildForProfiling = "NO" buildForArchiving = "NO" buildForAnalyzing = "NO">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{project_targets[name]}" BuildableName = "{name}.xctest" BlueprintName = "{name}" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </BuildActionEntry>'''
        for name in test_targets
    )
    testables = "\n".join(
        f'''      <TestableReference skipped = "NO">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{project_targets[name]}" BuildableName = "{name}.xctest" BlueprintName = "{name}" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </TestableReference>'''
        for name in test_targets
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "2700" version = "1.7">
  <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </BuildActionEntry>
{build_test_entries}
    </BuildActionEntries>
  </BuildAction>
    <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES" codeCoverageEnabled = "YES" onlyGenerateCoverageForSpecifiedTargets = "NO">
    <MacroExpansion>
      <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj">
      </BuildableReference>
    </MacroExpansion>
    <Testables>
{testables}
    </Testables>
    <CommandLineArguments>
      <CommandLineArgument argument = "--patient-app-deterministic-client" isEnabled = "YES"/>
    </CommandLineArguments>
  </TestAction>
  <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
    <BuildableProductRunnable runnableDebuggingMode = "0">
      <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj">
      </BuildableReference>
    </BuildableProductRunnable>
    <MacroExpansion>
      <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj">
      </BuildableReference>
    </MacroExpansion>
  </LaunchAction>
  <ProfileAction buildConfiguration = "Release" shouldUseLaunchSchemeArgsEnv = "YES" savedToolIdentifier = "" useCustomWorkingDirectory = "NO" debugDocumentVersioning = "YES">
    <BuildableProductRunnable runnableDebuggingMode = "0">
      <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj">
      </BuildableReference>
    </BuildableProductRunnable>
    <MacroExpansion>
      <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app_id}" BuildableName = "PatientApp.app" BlueprintName = "PatientApp" ReferencedContainer = "container:PatientApp.xcodeproj">
      </BuildableReference>
    </MacroExpansion>
  </ProfileAction>
  <AnalyzeAction buildConfiguration = "Debug"/>
  <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES"/>
</Scheme>
'''


def domain_scheme(project_targets: dict[str, str]) -> str:
    domain_id = project_targets["PatientAppDomain"]
    tests_id = project_targets["PatientAppDomainTests"]
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "2700" version = "1.7">
  <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting = "YES" buildForRunning = "NO" buildForProfiling = "NO" buildForArchiving = "NO" buildForAnalyzing = "YES">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{domain_id}" BuildableName = "PatientAppDomain.framework" BlueprintName = "PatientAppDomain" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </BuildActionEntry>
      <BuildActionEntry buildForTesting = "YES" buildForRunning = "NO" buildForProfiling = "NO" buildForArchiving = "NO" buildForAnalyzing = "NO">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{tests_id}" BuildableName = "PatientAppDomainTests.xctest" BlueprintName = "PatientAppDomainTests" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </BuildActionEntry>
    </BuildActionEntries>
  </BuildAction>
  <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES" codeCoverageEnabled = "YES" onlyGenerateCoverageForSpecifiedTargets = "NO">
    <Testables>
      <TestableReference skipped = "NO">
        <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{tests_id}" BuildableName = "PatientAppDomainTests.xctest" BlueprintName = "PatientAppDomainTests" ReferencedContainer = "container:PatientApp.xcodeproj"/>
      </TestableReference>
    </Testables>
  </TestAction>
  <AnalyzeAction buildConfiguration = "Debug"/>
  <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES"/>
</Scheme>
'''


def main() -> None:
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    SCHEMES.mkdir(parents=True, exist_ok=True)

    names = ["PatientAppDomain", "PatientAppUI", "PatientApp", "PatientAppDomainTests", "PatientAppUITests", "PatientAppLaunchUITests"]
    targets = {name: uid(f"target:{name}") for name in names}
    groups = {}
    group_objects = []
    for label, path in [("PatientAppDomain", "Sources/PatientAppDomain"), ("PatientAppUI", "Sources/PatientAppUI"), ("PatientApp", "Sources/PatientApp"), ("PatientAppDomainTests", "Tests/PatientAppDomainTests"), ("PatientAppUITests", "Tests/PatientAppUITests"), ("PatientAppLaunchUITests", "UITests"), ("Resources", "Resources")]:
        groups[label], obj = fs_group(label, path)
        group_objects.append(obj)

    product_ids = {}
    product_objects = []
    product_types = {
        "PatientAppDomain": ("framework", "wrapper.framework"),
        "PatientAppUI": ("framework", "wrapper.framework"),
        "PatientApp": ("app", "wrapper.application"),
        "PatientAppDomainTests": ("xctest", "wrapper.cfbundle"),
        "PatientAppUITests": ("xctest", "wrapper.cfbundle"),
        "PatientAppLaunchUITests": ("xctest", "wrapper.cfbundle"),
    }
    for name, (extension, file_type) in product_types.items():
        product_ids[name] = uid(f"product:{name}")
        product_objects.append(file_ref(product_ids[name], f"{name}.{extension}", f"{name}.{extension}", file_type))

    products_group = uid("group:Products")
    main_group = uid("group:Main")
    group_objects.append(textwrap.dedent(f"""\
        {products_group} /* Products */ = {{
            isa = PBXGroup;
            children = (
        {''.join(f'\t\t\t{product_ids[name]} /* {name} */,\n' for name in names)}
            );
            name = Products;
            sourceTree = \"<group>\";
        }};
        {main_group} /* PatientApp */ = {{
            isa = PBXGroup;
            children = (
        {''.join(f'\t\t\t{groups[label]} /* {label} */,\n' for label in groups)}
                {products_group} /* Products */,
            );
            sourceTree = \"<group>\";
        }};
    """))

    phase_objects = []
    phases = {}
    for name in names:
        src = uid(f"phase:sources:{name}")
        fw = uid(f"phase:frameworks:{name}")
        rs = uid(f"phase:resources:{name}")
        phase_objects.extend([phase(src, "PBXSourcesBuildPhase", f"Sources for {name}"), phase(fw, "PBXFrameworksBuildPhase", f"Frameworks for {name}")])
        phases[name] = [src, fw]
        if name == "PatientApp":
            phase_objects.append(phase(rs, "PBXResourcesBuildPhase", "Resources for PatientApp"))
            phases[name].append(rs)

    framework_builds = []
    frameworks_for = {"PatientAppUI": ["PatientAppDomain"], "PatientApp": ["PatientAppUI", "PatientAppDomain"], "PatientAppUITests": ["PatientAppUI", "PatientAppDomain"], "PatientAppDomainTests": ["PatientAppDomain"], "PatientAppLaunchUITests": []}
    for owner, deps in frameworks_for.items():
        framework_phase = phases[owner][1]
        for dep_name in deps:
            build_id = uid(f"build:{owner}:{dep_name}")
            framework_builds.append(build_file(build_id, product_ids[dep_name], f"{dep_name}.framework"))
        # Replace the empty framework phase with its build file identifiers.
        for index, obj in enumerate(phase_objects):
            if f"{framework_phase} /* Frameworks for {owner} */" in obj:
                ids = [uid(f"build:{owner}:{dep_name}") for dep_name in deps]
                phase_objects[index] = phase(framework_phase, "PBXFrameworksBuildPhase", f"Frameworks for {owner}", ids)
                break

    embed_phase = uid("phase:embed:PatientApp")
    embedded_ids = []
    for dep_name in frameworks_for["PatientApp"]:
        build_id = uid(f"embed:PatientApp:{dep_name}")
        embedded_ids.append(build_id)
        framework_builds.append(embedded_build_file(build_id, product_ids[dep_name], f"{dep_name}.framework (Embed)"))
    phase_objects.append(copy_phase(embed_phase, "Embed Frameworks", embedded_ids))
    phases["PatientApp"].append(embed_phase)

    project_id = uid("project")
    proxy_objects = []
    dependency_objects = []
    dependency_map = {name: [] for name in names}
    for owner, dep_name in [("PatientAppUI", "PatientAppDomain"), ("PatientApp", "PatientAppUI"), ("PatientApp", "PatientAppDomain"), ("PatientAppDomainTests", "PatientAppDomain"), ("PatientAppUITests", "PatientAppUI"), ("PatientAppUITests", "PatientAppDomain"), ("PatientAppLaunchUITests", "PatientApp")]:
        proxy_id = uid(f"proxy:{owner}:{dep_name}")
        dep_id = uid(f"dependency:{owner}:{dep_name}")
        proxy_objects.append(textwrap.dedent(f"""\
            {proxy_id} /* PBXContainerItemProxy */ = {{
                isa = PBXContainerItemProxy;
                containerPortal = {project_id} /* Project object */;
                proxyType = 1;
                remoteGlobalIDString = {targets[dep_name]};
                remoteInfo = {q(dep_name)};
            }};
        """))
        dependency_objects.append(textwrap.dedent(f"""\
            {dep_id} /* {dep_name} */ = {{
                isa = PBXTargetDependency;
                target = {targets[dep_name]} /* {dep_name} */;
                targetProxy = {proxy_id} /* PBXContainerItemProxy */;
            }};
        """))
        dependency_map[owner].append(dep_id)

    configs = []
    config_lists = {}
    for label in ["PROJECT", *names]:
        debug_id, release_id = uid(f"config:{label}:Debug"), uid(f"config:{label}:Release")
        if label == "PROJECT":
            debug_settings = release_settings = project_settings()
        else:
            debug_settings = target_settings({"PatientAppDomain": "com.johannisxu.uspatientapp.domain", "PatientAppUI": "com.johannisxu.uspatientapp.ui", "PatientApp": "com.johannisxu.uspatientapp", "PatientAppDomainTests": "com.johannisxu.uspatientapp.domainTests", "PatientAppUITests": "com.johannisxu.uspatientapp.uiTests", "PatientAppLaunchUITests": "com.johannisxu.uspatientapp.launchUITests"}[label], label, app=label == "PatientApp", test=label.endswith("Tests"), ui_test=label == "PatientAppLaunchUITests")
            release_settings = dict(debug_settings)
            debug_settings["DEBUG_INFORMATION_FORMAT"] = "dwarf"
            release_settings["DEBUG_INFORMATION_FORMAT"] = q("dwarf-with-dsym")
        configs.extend([config(debug_id, "Debug", debug_settings), config(release_id, "Release", release_settings)])
        config_lists[label] = uid(f"config-list:{label}")
        configs.append(config_list(config_lists[label], debug_id, release_id, "Project" if label == "PROJECT" else label))

    target_objects = []
    product_type_names = {
        "PatientAppDomain": "com.apple.product-type.framework",
        "PatientAppUI": "com.apple.product-type.framework",
        "PatientApp": "com.apple.product-type.application",
        "PatientAppDomainTests": "com.apple.product-type.bundle.unit-test",
        "PatientAppUITests": "com.apple.product-type.bundle.unit-test",
        "PatientAppLaunchUITests": "com.apple.product-type.bundle.ui-testing",
    }
    for name in names:
        target_groups = [groups[name]]
        target_objects.append(target(targets[name], name, product_ids[name], product_type_names[name], config_lists[name], phases[name], target_groups, dependency_map[name]))

    project_object = textwrap.dedent(f"""\
        {project_id} /* Project object */ = {{
            isa = PBXProject;
            attributes = {{
                BuildIndependentTargetsInParallel = 1;
                LastUpgradeCheck = 2700;
                TargetAttributes = {{
                    {targets['PatientApp']} = {{ CreatedOnToolsVersion = 27.0; }};
                }};
            }};
            buildConfigurationList = {config_lists['PROJECT']} /* Build configuration list for Project */;
            developmentRegion = en;
            hasScannedForEncodings = 0;
            knownRegions = (en, Base, "zh-Hans",);
            mainGroup = {main_group};
            minimizedProjectReferenceProxies = 1;
            preferredProjectObjectVersion = 90;
            productRefGroup = {products_group} /* Products */;
            projectDirPath = \"\";
            projectRoot = \"\";
            targets = (
        {''.join(f'\t\t\t{targets[name]} /* {name} */,\n' for name in names)}
            );
        }};
    """)

    contents = "// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n\tobjectVersion = 90;\n\tobjects = {\n"
    contents += "\n".join(product_objects) + "\n".join(group_objects) + "\n".join(framework_builds) + "\n".join(phase_objects) + "\n".join(configs) + "\n".join(proxy_objects) + "\n".join(dependency_objects) + "\n".join(target_objects) + project_object
    contents += f"\t}};\n\trootObject = {project_id} /* Project object */;\n}}\n"
    # Xcode accepts either indentation style, but git's whitespace checker
    # rejects spaces before tabs in generated project files.
    contents = re.sub(r"(?m)^ +\t", "\t", contents)
    PROJECT.mkdir(parents=True, exist_ok=True)
    (PROJECT / "project.pbxproj").write_text(contents)
    SCHEMES.mkdir(parents=True, exist_ok=True)
    (SCHEMES / "PatientApp-Debug.xcscheme").write_text(scheme(targets, ["PatientAppDomainTests", "PatientAppUITests", "PatientAppLaunchUITests"]))
    (SCHEMES / "PatientAppTests.xcscheme").write_text(scheme(targets, ["PatientAppDomainTests", "PatientAppUITests", "PatientAppLaunchUITests"]))
    (SCHEMES / "PatientAppDomain.xcscheme").write_text(domain_scheme(targets))
    print(PROJECT)


if __name__ == "__main__":
    main()
