% Copyright (c) 2019 Surjyendu Ray
% 
% This program is free software: you can redistribute it and/or modify
% it under the terms of the GNU General Public License as published by
% the Free Software Foundation, either version 3 of the License, or
% (at your option) any later version.
% 
% This program is distributed in the hope that it will be useful,
% but WITHOUT ANY WARRANTY; without even the implied warranty of
% MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
% GNU General Public License for more details.

%% Comparing ground truth and output of AncesTree across all 90 files
% calculate 4 error types from U matrices and clustering information for
% inferred tree vs ground truth tree, for all 90 simulated files, provided in the AncesTree paper

% OUTPUTS
% error_rates = error rates is an array object with 4 rows, each row containing the value of a particular error type. 
% all_error_of_ancestry_relations = array collecting the error_rates array for all 90 simulated files, for AncesTree.


all_error_of_ancestry_relations = [ ];

for file_count_id = 1:90
	
	% INPUTS
	% Loading the AncesTree results on each of the simulated data files 
    path_to_sim_ances_tree_data = '/home/surjray/Phylogeny_repo/phylogenetic_tree_software_with_matlab_wrappers/all_tests/Sample_test_data/AncesTree_data/simulated/';
    list_of_dirs = dir(path_to_sim_ances_tree_data);
    count = 0;
    found_flag = 0;
    for i = 3:length(list_of_dirs)
        list_of_fildes = dir([path_to_sim_ances_tree_data,list_of_dirs(i).name,'/*.true']);
        for j = 1:length(list_of_fildes)
            count = count + 1;
            if (count == file_count_id)
                ground_truth_file = [path_to_sim_ances_tree_data,list_of_dirs(i).name,'/',list_of_fildes(j).name];
                found_flag = 1;
                break;
            end
            if (found_flag == 1)
                break;
            end
        end
    end


    [true_tree_data] =  read_ground_truth_from_elkebir_data(ground_truth_file);
    ancestree_output = load('/home/surjray/Phylogeny_repo/phylogenetic_tree_software_with_matlab_wrappers/all_tests/all_results/all_ancestree_outputs_on_synthetic_Elkebir_data.mat','all_ancestree_outputs');
    ancestree_output = ancestree_output.all_ancestree_outputs{file_count_id};

    U1 = true_tree_data{3}';
    clust1 = true_tree_data{5};

    U2 = ancestree_output{3}{1};
    U2 = inv(eye(length(U2)) - U2);
    clust2 = [];
    for i = 1:length(ancestree_output{4}{1})
        for j = ancestree_output{4}{1}{i}'
        clust2 = [clust2; [j,i]];
        end
    end

    [error_rates] = compare_trees_using_U_matrices_and_clustering(U1, clust1, U2, clust2);

    all_error_of_ancestry_relations = [all_error_of_ancestry_relations , error_rates(2)];
	plot(all_error_of_ancestry_relations, '*');
    drawnow;
end